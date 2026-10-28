"""Deliberate, documented data-quality anomalies injected into synthetic source files.

Each kind is applied to at most one distinct loan per vintage and recorded, so ingest and
data-quality tests can assert that every injected problem is detected exactly once. Kinds mirror
CLAUDE.md §5 and MODELING §2: orphan rows, duplicate periods, gaps, undocumented codes, activity
after termination, same-month modification + termination and missing effective dates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pyarrow as pa

from prepay import periods
from prepay.synthetic.simulate import loan_identifiers

KINDS = (
    "orphan_performance",
    "duplicate_exact_period",
    "duplicate_conflicting_period",
    "missing_period_gap",
    "invalid_zero_balance_code",
    "rows_after_termination",
    "modification_with_terminal_same_month",
    "missing_zero_balance_effective_date",
    "duplicate_origination",
)


@dataclass(frozen=True, slots=True)
class Anomaly:
    kind: str
    loan_id: str
    period: str  # YYYYMM of the affected performance row ("" for origination anomalies)
    rows: int  # performance or origination rows added (+), removed (-) or edited (0)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class _TableEditor:
    """Row-level edits on an Arrow string table without materializing Python rows."""

    def __init__(self, table: pa.Table) -> None:
        self.table = table
        self.order: list[int] = list(range(table.num_rows))
        self.extra: list[pa.Table] = []

    def _copy(self, row: int, changes: dict[str, str]) -> int:
        piece = self.table.slice(row, 1)
        for name, value in changes.items():
            index = piece.schema.get_field_index(name)
            piece = piece.set_column(index, name, pa.array([value], type=pa.string()))
        self.extra.append(piece)
        return int(self.table.num_rows) + len(self.extra) - 1

    def edit(self, row: int, changes: dict[str, str]) -> None:
        self.order[self.order.index(row)] = self._copy(row, changes)

    def insert_after(self, row: int, changes: dict[str, str]) -> None:
        self.order.insert(self.order.index(row) + 1, self._copy(row, changes))

    def remove(self, row: int) -> None:
        self.order.remove(row)

    def append(self, row: int, changes: dict[str, str]) -> None:
        self.order.append(self._copy(row, changes))

    def result(self) -> pa.Table:
        combined = pa.concat_tables([self.table, *self.extra])
        return combined.take(pa.array(self.order, type=pa.int64()))


def _next_month(yyyymm: str) -> str:
    return periods.to_yyyymm(periods.parse_yyyymm(yyyymm) + 1)


def inject(
    rng: np.random.Generator, vintage: int, origination: pa.Table, performance: pa.Table
) -> tuple[pa.Table, pa.Table, list[Anomaly]]:
    """Return modified copies of the block-0 tables plus the list of applied anomalies."""
    loan = np.asarray(performance["loan_id"].to_numpy(zero_copy_only=False))
    period = np.asarray(performance["period"].to_numpy(zero_copy_only=False))
    zb = np.asarray(performance["zero_balance_code"].to_numpy(zero_copy_only=False))
    starts = np.flatnonzero(np.r_[True, loan[1:] != loan[:-1]])
    ends = np.r_[starts[1:], loan.size]
    spans = {str(loan[s]): (int(s), int(e)) for s, e in zip(starts, ends, strict=True)}
    last_code = {lid: str(zb[e - 1]) for lid, (_, e) in spans.items()}

    used: set[str] = set()
    applied: list[Anomaly] = []
    perf = _TableEditor(performance)

    def pick(candidates: list[str]) -> str | None:
        pool = sorted(set(candidates) - used)
        if not pool:
            return None
        choice = pool[int(rng.integers(len(pool)))]
        used.add(choice)
        return choice

    long_active = [lid for lid, (s, e) in spans.items() if e - s >= 5 and last_code[lid] == ""]
    long_any = [lid for lid, (s, e) in spans.items() if e - s >= 3]
    paid_off = [lid for lid in spans if last_code[lid] == "01"]
    terminal_not_defect = [lid for lid in spans if last_code[lid] not in ("", "96")]

    if (lid := pick(long_any)) is not None:
        s, _ = spans[lid]
        orphan = loan_identifiers(
            vintage, np.array([periods.month(vintage, 1)]), np.array([9_000_000])
        )[0]
        for row in range(s, s + 3):
            perf.append(row, {"loan_id": orphan})
        applied.append(Anomaly("orphan_performance", orphan, str(period[s]), 3))
    if (lid := pick(long_active)) is not None:
        s, e = spans[lid]
        row = (s + e) // 2
        perf.insert_after(row, {})
        applied.append(Anomaly("duplicate_exact_period", lid, str(period[row]), 1))
    if (lid := pick(long_active)) is not None:
        s, e = spans[lid]
        row = (s + e) // 2
        upb = float(performance["current_actual_upb"][row].as_py()) + 1000.0
        perf.insert_after(row, {"current_actual_upb": f"{upb:.2f}"})
        applied.append(Anomaly("duplicate_conflicting_period", lid, str(period[row]), 1))
    if (lid := pick(long_active)) is not None:
        s, e = spans[lid]
        row = (s + e) // 2
        perf.remove(row)
        applied.append(Anomaly("missing_period_gap", lid, str(period[row]), -1))
    if (lid := pick(paid_off)) is not None:
        row = spans[lid][1] - 1
        perf.edit(row, {"zero_balance_code": "06"})
        applied.append(Anomaly("invalid_zero_balance_code", lid, str(period[row]), 0))
    if (lid := pick(terminal_not_defect)) is not None:
        row = spans[lid][1] - 1
        perf.insert_after(
            row,
            {
                "period": _next_month(str(period[row])),
                "zero_balance_code": "",
                "zero_balance_effective_date": "",
            },
        )
        applied.append(Anomaly("rows_after_termination", lid, _next_month(str(period[row])), 1))
    if (lid := pick(paid_off)) is not None:
        row = spans[lid][1] - 1
        perf.edit(row, {"modification_flag": "Y"})
        applied.append(Anomaly("modification_with_terminal_same_month", lid, str(period[row]), 0))
    if (lid := pick(terminal_not_defect)) is not None:
        row = spans[lid][1] - 1
        perf.edit(row, {"zero_balance_effective_date": ""})
        applied.append(Anomaly("missing_zero_balance_effective_date", lid, str(period[row]), 0))

    orig = _TableEditor(origination)
    orig_ids = origination["loan_id"].to_pylist()
    if (lid := pick([str(x) for x in orig_ids])) is not None:
        row = orig_ids.index(lid)
        orig.append(row, {"credit_score": "640"})
        applied.append(Anomaly("duplicate_origination", lid, "", 1))
    return orig.result(), perf.result(), applied
