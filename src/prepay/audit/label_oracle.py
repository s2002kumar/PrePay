"""Independent Python re-implementation of quarantine rules and the MODELING §2 decision table.

Reads the bronze Parquet directly (not the dbt staging layer) and applies the rules with plain
loops, so a shared SQL misconception cannot make both sides agree. ``buckets`` restricts it to the
loans whose ``hash(loan_id) % LOAN_HASH_BUCKETS`` falls in ``[low, high)``, the same stable hash as
panel sampling, so full-sample audits run in disjoint slices of bounded memory.
"""

from __future__ import annotations

import collections
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from prepay import periods
from prepay.contracts.sflld import PERFORMANCE
from prepay.features.panel import LOAN_HASH_BUCKETS

MATURITY_WINDOW = 2


@dataclass(frozen=True)
class OracleResult:
    quarantined: set[str]
    excluded: set[str]
    events: dict[str, tuple[str, int]]  # loan_id -> (event_type, event_month)
    panel: dict[tuple[str, int], str]  # (loan_id, target_month) -> outcome


def _month(text: str) -> int | None:
    try:
        return periods.parse_yyyymm(text)
    except ValueError:
        return None


def bucket_clause(buckets: tuple[int, int] | None) -> str:
    if buckets is None:
        return "true"
    low, high = buckets
    if not 0 <= low < high <= LOAN_HASH_BUCKETS:
        raise ValueError(f"buckets must satisfy 0 <= low < high <= {LOAN_HASH_BUCKETS}")
    bucket = f"hash(loan_id) % {LOAN_HASH_BUCKETS}"
    return f"{bucket} >= {low} and {bucket} < {high}"


def run(bronze: Path, cutoff_month: int, buckets: tuple[int, int] | None = None) -> OracleResult:
    con = duckdb.connect()
    root = bronze.as_posix()
    where = bucket_clause(buckets)
    orig_rows = con.sql(
        f"select loan_id, first_payment_date, maturity_date, original_interest_rate, "  # noqa: S608
        f"original_upb, original_loan_term, amortization_type, interest_only, _violations "
        f"from read_parquet('{root}/sflld/*/*/origination.parquet', hive_partitioning=false) "
        f"where {where}"
    ).fetchall()
    perf_rows = con.sql(
        f"select * exclude (_source_file) "  # noqa: S608
        f"from read_parquet('{root}/sflld/*/*/performance.parquet', hive_partitioning=false) "
        f"where {where}"
    ).fetchall()
    perf_columns = [
        d[0]
        for d in con.sql(
            f"select * exclude (_source_file) "  # noqa: S608
            f"from read_parquet('{root}/sflld/*/*/performance.parquet', hive_partitioning=false) "
            f"limit 0"
        ).description
    ]
    col = {name: i for i, name in enumerate(perf_columns)}

    origination: dict[str, list[tuple[Any, ...]]] = collections.defaultdict(list)
    for row in orig_rows:
        origination[row[0]].append(row)
    performance: dict[str, list[tuple[Any, ...]]] = collections.defaultdict(list)
    for row in perf_rows:
        performance[row[col["loan_id"]]].append(row)

    quarantined: set[str] = set()
    excluded: set[str] = set()
    for loan_id in set(origination) | set(performance):
        o = origination.get(loan_id, [])
        p = sorted(performance.get(loan_id, []), key=lambda r: r[col["_source_row"]])
        reasons = []
        if not o:
            reasons.append("orphan")
        if not p:
            reasons.append("no_performance")
        if len(o) > 1:
            reasons.append("duplicate_origination")
        if any(r[-1] != 0 for r in o) or any(r[col["_violations"]] != 0 for r in p):
            reasons.append("violation")
        if o and (
            _month(o[0][1]) is None or _month(o[0][2]) is None or "" in (o[0][3], o[0][4], o[0][5])
        ):
            reasons.append("missing_required")
        by_period: dict[str, set[tuple[Any, ...]]] = collections.defaultdict(set)
        for r in p:
            business = tuple(r[: PERFORMANCE.width])  # raw fields only, not lineage
            by_period[r[col["period"]]].add(business)
        if any(len(v) > 1 for v in by_period.values()):
            reasons.append("conflicting_duplicate")
        months = sorted(m for m in (_month(k) for k in by_period) if m is not None)
        if len(months) != len(by_period):
            reasons.append("bad_period")
        if any(b - a > 1 for a, b in itertools.pairwise(months)):
            reasons.append("gap")
        terminal = sorted(
            m
            for m in (_month(r[col["period"]]) for r in p if r[col["zero_balance_code"]] != "")
            if m is not None  # an unparseable period is already quarantined as bad_period
        )
        if terminal and any(m > terminal[0] for m in months):
            reasons.append("after_termination")
        if len(terminal) > 1:
            reasons.append("multiple_terminal")
        for r in p:
            if r[col["zero_balance_code"]] != "" and r[col["modification_flag"]] == "Y":
                reasons.append("mod_with_terminal")
            if r[col["zero_balance_code"]] != "" and r[col["zero_balance_effective_date"]] == "":
                reasons.append("missing_zb_date")
        if reasons:
            quarantined.add(loan_id)
            continue
        first = min(p, key=lambda r: _month(r[col["period"]]) or 0)
        if first[col["modification_flag"]] == "P" or o[0][6] != "FRM" or o[0][7] == "Y":
            excluded.add(loan_id)

    events: dict[str, tuple[str, int]] = {}
    panel: dict[tuple[str, int], str] = {}
    for loan_id, rows in performance.items():
        if loan_id in quarantined or loan_id in excluded:
            continue
        first_payment = _month(origination[loan_id][0][1])
        maturity = _month(origination[loan_id][0][2])
        assert first_payment is not None
        assert maturity is not None
        states: dict[int, tuple[Any, ...]] = {}
        for r in sorted(rows, key=lambda r: r[col["_source_row"]]):
            month = _month(r[col["period"]])
            assert month is not None  # loans with unparseable periods were quarantined
            states.setdefault(month, r)  # first source row wins
        ordered = sorted(states)
        event, event_month = None, None
        for m in ordered:
            r = states[m]
            if r[col["modification_flag"]] == "Y":
                event, event_month = "censor_modification", m
                break
            code = r[col["zero_balance_code"]]
            if code:
                if code == "01":
                    event = "maturity" if maturity - m <= MATURITY_WINDOW else "prepay"
                else:
                    event = {
                        "02": "credit",
                        "03": "credit",
                        "09": "credit",
                        "15": "censor_whole_loan_sale",
                        "16": "censor_reperforming_securitization",
                        "96": "censor_defect",
                    }[code]
                event_month = m
                break
        if event is None:
            event_month = ordered[-1]
            event = (
                "censor_administrative" if event_month == cutoff_month else "censor_unexplained_end"
            )
        assert event_month is not None
        events[loan_id] = (event, event_month)
        for previous, current in itertools.pairwise(ordered):
            prior = states[previous]
            if current > event_month:
                break
            if (
                prior[col["zero_balance_code"]] == ""
                and float(prior[col["current_actual_upb"]]) > 0
                and previous >= first_payment
            ):
                if current == event_month and event not in (
                    "prepay",
                    "credit",
                    "censor_administrative",
                    "censor_unexplained_end",
                ):
                    continue
                outcome = "A"
                if current == event_month and event == "prepay":
                    outcome = "P"
                elif current == event_month and event == "credit":
                    outcome = "C"
                panel[(loan_id, current)] = outcome
    return OracleResult(quarantined, excluded, events, panel)
