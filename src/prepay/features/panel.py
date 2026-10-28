"""Read the gold hazard panel, loan statics and rate paths in bounded, typed batches.

Values are returned in the representation of :func:`prepay.features.machine.compute_features`:
numeric features as float64 with NaN for missing, flags as 0/1 floats, categoricals as object
arrays with None for missing. Reads select only needed columns, filter by target-month window, and
can sample whole loans deterministically (stable hash of the loan ID), never individual rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import numpy.typing as npt
import pyarrow as pa

from prepay.arrays import FloatArray, IntArray
from prepay.features.machine import LoanStatics, ObjectArray, RatePath
from prepay.features.spec import CATEGORICAL, FEATURES, NUMERIC

LOAN_HASH_BUCKETS = 10_000


@dataclass(frozen=True, slots=True)
class PanelBatch:
    loan_id: ObjectArray
    target_month: IntArray
    outcome_class: IntArray  # 0 = active, 1 = voluntary payoff, 2 = credit disposition
    exposure_upb: FloatArray
    features: dict[str, npt.NDArray[np.float64] | ObjectArray]

    @property
    def rows(self) -> int:
        return int(self.target_month.shape[0])


def _numeric(column: pa.ChunkedArray) -> FloatArray:
    if pa.types.is_boolean(column.type):
        column = column.cast(pa.float64())
    return np.asarray(column.cast(pa.float64()).to_numpy(zero_copy_only=False), dtype=np.float64)


def _categorical(column: pa.ChunkedArray) -> ObjectArray:
    return np.asarray(column.to_pylist(), dtype=object)


def sample_clause(sample_fraction: float | None) -> str:
    """Loan-consistent deterministic sample: keep a loan iff hash(loan_id) falls in the bucket."""
    if sample_fraction is None:
        return "true"
    if not 0.0 < sample_fraction <= 1.0:
        raise ValueError("sample_fraction must lie in (0, 1]")
    if sample_fraction == 1.0:
        return "true"
    kept = round(sample_fraction * LOAN_HASH_BUCKETS)
    return f"hash(loan_id) % {LOAN_HASH_BUCKETS} < {kept}"


def read_panel(
    con: duckdb.DuckDBPyConnection,
    first_month: int,
    last_month: int,
    *,
    sample_fraction: float | None = None,
) -> PanelBatch:
    """Rows with ``first_month <= target_month <= last_month`` (month indices, inclusive)."""
    columns = ", ".join(
        ["loan_id", "target_month", "outcome_class", "exposure_upb", *(f.name for f in FEATURES)]
    )
    table = con.sql(
        f"select {columns} from fct_hazard_panel "  # noqa: S608 - fixed identifiers only
        f"where target_month between $first and $last and {sample_clause(sample_fraction)} "
        "order by loan_id, target_month",
        params={"first": first_month, "last": last_month},
    ).to_arrow_table()
    features: dict[str, npt.NDArray[np.float64] | ObjectArray] = {}
    for name in NUMERIC:
        features[name] = _numeric(table[name])
    for name in CATEGORICAL:
        values = _categorical(table[name])
        if name == "month_of_year":
            values = np.asarray([None if v is None else int(v) for v in values], dtype=object)
        features[name] = values
    return PanelBatch(
        loan_id=_categorical(table["loan_id"]),
        target_month=np.asarray(table["target_month"].to_numpy(), dtype=np.int64),
        outcome_class=np.asarray(table["outcome_class"].to_numpy(), dtype=np.int64),
        exposure_upb=_numeric(table["exposure_upb"]),
        features=features,
    )


def load_statics(con: duckdb.DuckDBPyConnection) -> tuple[ObjectArray, LoanStatics]:
    """Static attributes of every eligible loan (``int_loans``), ordered by loan ID."""
    table = con.sql(
        "select loan_id, note_rate_pct, original_loan_term, first_payment_month, maturity_month, "
        "original_upb, credit_score, original_ltv, original_dti, mi_pct, number_of_units, "
        "number_of_borrowers, loan_purpose, occupancy_status, channel, first_time_homebuyer, "
        "property_type, property_state from int_loans order by loan_id"
    ).to_arrow_table()

    def ints(name: str) -> IntArray:
        return np.asarray(table[name].to_numpy(), dtype=np.int64)

    statics = LoanStatics(
        note_rate_pct=_numeric(table["note_rate_pct"]),
        original_loan_term=ints("original_loan_term"),
        first_payment_month=ints("first_payment_month"),
        maturity_month=ints("maturity_month"),
        original_upb=_numeric(table["original_upb"]),
        credit_score=_numeric(table["credit_score"]),
        original_ltv=_numeric(table["original_ltv"]),
        original_dti=_numeric(table["original_dti"]),
        mi_pct=_numeric(table["mi_pct"]),
        number_of_units=_numeric(table["number_of_units"]),
        number_of_borrowers=_numeric(table["number_of_borrowers"]),
        loan_purpose=_categorical(table["loan_purpose"]),
        occupancy_status=_categorical(table["occupancy_status"]),
        channel=_categorical(table["channel"]),
        first_time_homebuyer=_categorical(table["first_time_homebuyer"]),
        property_type=_categorical(table["property_type"]),
        property_state=_categorical(table["property_state"]),
    )
    return _categorical(table["loan_id"]), statics


def rate_path_from_bronze(bronze_root: Path) -> RatePath:
    """Month-end as-of rate path computed in Python from the weekly bronze observations."""
    series = {}
    for name in ("MORTGAGE30US", "MORTGAGE15US"):
        path = (bronze_root / "pmms" / f"series={name}" / "observations.parquet").as_posix()
        rows = duckdb.execute(
            "select observation_date, rate_pct from read_parquet(?, hive_partitioning=false) "
            "order by observation_date",
            [path],
        ).fetchall()
        series[name] = ([r[0] for r in rows], [r[1] for r in rows])
    return RatePath.from_weekly(*series["MORTGAGE30US"], *series["MORTGAGE15US"])
