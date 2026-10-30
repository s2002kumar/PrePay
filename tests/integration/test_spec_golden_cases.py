"""Golden cases for the event definitions, written from the specification, not from either
implementation (R2 independent-oracle audit).

Each case edits one clean synthetic loan's history to match one row of the MODELING §2 decision
table (ADR 0003 for operational details). The expected outcome is stated from the spec text in
terms of the edited row ``k``:

- the loan's status (kept, quarantined or excluded);
- its exit event type;
- the exact set of labeled panel months.

The dbt SQL **and** the independent Python label oracle must both reproduce every case. This
doesn't make the audit independent of its author (the same agent wrote all three). It does mean
the expected values come from the decision table, not from code.
"""

from __future__ import annotations

import collections
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pytest

from prepay import periods
from prepay.audit import label_oracle
from prepay.contracts.sflld import ORIGINATION, PERFORMANCE
from prepay.ingest import ingest_all
from prepay.ingest.lock import create_lock
from prepay.transform import run_dbt, warehouse_path

P = {f.name: i for i, f in enumerate(PERFORMANCE.fields)}
ORIG = {f.name: i for i, f in enumerate(ORIGINATION.fields)}
K = 10  # the edited row: well past the first payment month
CUTOFF = periods.month(2026, 6)
Rows = list[list[str]]


def _month(row: list[str]) -> int:
    return periods.parse_yyyymm(row[P["period"]])


def terminal(code: str, *, effective: bool = True) -> Callable[[Rows], Rows]:
    """Row K becomes a zero-balance record with ``code``; later rows are dropped."""

    def build(rows: Rows) -> Rows:
        out = [list(r) for r in rows[: K + 1]]
        row = out[K]
        row[P["zero_balance_removal_upb"]] = out[K - 1][P["current_actual_upb"]]
        row[P["current_actual_upb"]] = "0.00"
        row[P["current_interest_bearing_upb"]] = "0.00"
        row[P["zero_balance_code"]] = code
        row[P["zero_balance_effective_date"]] = row[P["period"]] if effective else ""
        row[P["ddlpi"]] = ""
        return out

    return build


def modified_at_k(rows: Rows) -> Rows:
    """'Y' at row K; the loan then continues under 'P' (a modified contract)."""
    out = [list(r) for r in rows]
    out[K][P["modification_flag"]] = "Y"
    for row in out[K + 1 :]:
        row[P["modification_flag"]] = "P"
    return out


def modified_and_paid_same_month(rows: Rows) -> Rows:
    out = terminal("01")(rows)
    out[K][P["modification_flag"]] = "Y"
    return out


def serious_delinquency_that_cures(rows: Rows) -> Rows:
    """90+ days delinquent for four months, then current again: not an event."""
    out = [list(r) for r in rows]
    for offset, status in enumerate(("03", "04", "05", "06")):
        out[K + offset][P["delinquency_status"]] = status
    return out


def records_end_early(rows: Rows) -> Rows:
    """The history stops at row K without any code, before the cutoff."""
    return [list(r) for r in rows[: K + 1]]


def month_missing(rows: Rows) -> Rows:
    return [list(r) for i, r in enumerate(rows) if i != K]


def modified_before_entry(rows: Rows) -> Rows:
    out = [list(r) for r in rows]
    for row in out:
        row[P["modification_flag"]] = "P"
    return out


@dataclass(frozen=True)
class Case:
    build: Callable[[Rows], Rows]
    status: str  # kept / quarantined / excluded
    event: str | None = None
    #: Last labeled month as a row index; "end" = the last row of the edited history.
    last_labeled: int | str | None = None
    final_label: str = "A"


CASES = {
    # MODELING §2: terminal 01 well before maturity -> P, labeled in its own month.
    "voluntary_payoff_01": Case(terminal("01"), "kept", "prepay", K, "P"),
    # 02 / 03 / 09 -> C, labeled in its own month.
    "third_party_sale_02": Case(terminal("02"), "kept", "credit", K, "C"),
    "short_sale_or_charge_off_03": Case(terminal("03"), "kept", "credit", K, "C"),
    "reo_disposition_09": Case(terminal("09"), "kept", "credit", K, "C"),
    # 15 / 16 / 96 -> right censor; the month of the record is excluded (ADR 0003 §5).
    "whole_loan_sale_15": Case(terminal("15"), "kept", "censor_whole_loan_sale", K - 1),
    "rpl_securitization_16": Case(
        terminal("16"), "kept", "censor_reperforming_securitization", K - 1
    ),
    "defect_96": Case(terminal("96"), "kept", "censor_defect", K - 1),
    # First modification 'Y' -> censor; its month and everything after are unlabeled.
    "modification_y": Case(modified_at_k, "kept", "censor_modification", K - 1),
    # 90+ delinquency is an observable state, never an event by itself.
    "delinquency_90_plus_cures": Case(
        serious_delinquency_that_cures, "kept", "censor_administrative", "end"
    ),
    # Records end without a code before the cutoff -> censored after the last active month.
    "unexplained_end": Case(records_end_early, "kept", "censor_unexplained_end", K),
    # Quarantine: same-month modification + terminal, terminal without effective date, a gap.
    "modification_and_terminal_same_month": Case(modified_and_paid_same_month, "quarantined"),
    "terminal_without_effective_date": Case(terminal("01", effective=False), "quarantined"),
    "missing_month": Case(month_missing, "quarantined"),
    # Prior modification 'P' at the first observation -> excluded at entry.
    "modified_before_entry": Case(modified_before_entry, "excluded"),
}


@pytest.fixture(scope="module")
def golden(
    tiny_dataset: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, dict[str, str], dict[str, Rows], dict[str, int]]:
    """Ingest and transform a copy of the tiny world with one clean loan edited per case."""
    import json

    tmp = tmp_path_factory.mktemp("golden")
    raw = tmp / "raw"
    shutil.copytree(tiny_dataset / "raw", raw)
    manifest = json.loads((tiny_dataset / "manifest.json").read_text(encoding="utf-8"))
    touched = {a["loan_id"] for v in manifest["vintages"] for a in v["anomalies"]}
    first_payment: dict[str, int] = {}
    histories: dict[str, tuple[str, Rows]] = {}
    for vintage in range(2008, 2016):
        archive = raw / "sflld" / f"sample_{vintage}.zip"
        with zipfile.ZipFile(archive) as z:
            perf = z.read(f"sample_perf_{vintage}.txt").decode("utf-8").splitlines()
            orig = z.read(f"sample_orig_{vintage}.txt").decode("utf-8").splitlines()
        for line in orig:
            fields = line.split("|")
            first_payment[fields[ORIG["loan_id"]]] = periods.parse_yyyymm(
                fields[ORIG["first_payment_date"]]
            )
        rows: dict[str, Rows] = collections.defaultdict(list)
        for line in perf:
            fields = line.split("|")
            rows[fields[0]].append(fields)
        for loan_id, history in rows.items():
            clean = (
                loan_id not in touched
                and len(history) >= 3 * K
                and _month(history[-1]) == CUTOFF
                and _month(history[0]) >= first_payment[loan_id]
                and all(
                    r[P["modification_flag"]] == r[P["zero_balance_code"]] == ""
                    and r[P["delinquency_status"]] == "00"
                    and r[P["payment_deferral_flag"]] == r[P["borrower_assistance_plan"]] == ""
                    for r in history
                )
            )
            if clean:
                histories[loan_id] = (f"sample_{vintage}.zip", history)
    if len(histories) < len(CASES):
        pytest.skip("the tiny world has too few clean long histories")
    chosen = dict(zip(CASES, sorted(histories)[: len(CASES)], strict=True))
    edited = {loan_id: CASES[case].build(histories[loan_id][1]) for case, loan_id in chosen.items()}
    by_archive: dict[str, set[str]] = collections.defaultdict(set)
    for loan_id in edited:
        by_archive[histories[loan_id][0]].add(loan_id)
    for archive, loans in by_archive.items():
        vintage = archive.removeprefix("sample_").removesuffix(".zip")
        path = raw / "sflld" / archive
        with zipfile.ZipFile(path) as src:
            contents = {name: src.read(name).decode("utf-8") for name in src.namelist()}
        member = f"sample_perf_{vintage}.txt"
        kept = [line for line in contents[member].splitlines() if line.split("|")[0] not in loans]
        kept += ["|".join(r) for loan_id in sorted(loans) for r in edited[loan_id]]
        contents[member] = "\n".join(kept) + "\n"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
            for name, text in contents.items():
                dst.writestr(zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)), text)
    lock = create_lock(
        raw, release=48, terms_reference="", synthetic_manifest=tiny_dataset / "manifest.json"
    )
    root = tmp / "root"
    ingest_all(raw, lock, root / "bronze")
    run_dbt(root, lock)
    return root, chosen, edited, first_payment


def _expected_panel(case: Case, rows: Rows) -> dict[int, str]:
    """Labeled months from the spec: every month after the first observed one, through the
    case's last labeled month; all 'A' except the final label of a P or C event."""
    months = [_month(r) for r in rows]
    last = len(rows) - 1 if case.last_labeled == "end" else int(str(case.last_labeled))
    panel = {months[j]: "A" for j in range(1, last + 1)}
    panel[months[last]] = case.final_label
    return panel


@pytest.mark.parametrize("name", list(CASES))
def test_both_implementations_reproduce_the_decision_table(
    name: str, golden: tuple[Path, dict[str, str], dict[str, Rows], dict[str, int]]
) -> None:
    root, chosen, edited, _ = golden
    case, loan_id = CASES[name], chosen[name]
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        quality = con.execute(
            "select is_quarantined, is_excluded from int_loan_quality where loan_id = ?",
            [loan_id],
        ).fetchone()
        sql_panel = dict(
            con.execute(
                "select target_month, outcome from fct_hazard_panel where loan_id = ?", [loan_id]
            ).fetchall()
        )
        sql_event = con.execute(
            "select event_type from int_exit_events where loan_id = ?", [loan_id]
        ).fetchone()
    oracle = label_oracle.run(root / "bronze", CUTOFF)
    oracle_panel = {m: o for (lid, m), o in oracle.panel.items() if lid == loan_id}

    assert quality is not None
    if case.status == "quarantined":
        assert quality[0] is True
        assert loan_id in oracle.quarantined
        assert sql_panel == oracle_panel == {}
        return
    if case.status == "excluded":
        assert (quality[0], quality[1]) == (False, True)
        assert loan_id in oracle.excluded
        assert sql_panel == oracle_panel == {}
        return
    assert (quality[0], quality[1]) == (False, False)
    expected = _expected_panel(case, edited[loan_id])
    assert sql_panel == expected
    assert oracle_panel == expected
    assert sql_event is not None
    assert sql_event[0] == case.event
    assert oracle.events[loan_id][0] == case.event
