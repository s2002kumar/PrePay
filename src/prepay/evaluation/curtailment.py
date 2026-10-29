"""Can partial principal prepayments (curtailments) be measured from the source? (F1)

A curtailment is principal paid beyond the scheduled installments. The source reports month-end
balances, not principal receipts, so a curtailment can only be *inferred*. For consecutive
months ``t-1``, ``t`` of a loan::

    residual_t = (B_{t-1} - B_t) - scheduled principal of the installments paid in month t

The method rests on three things that this module makes explicit, and each one can break it:

1. **Installments paid.** ``k_t`` = the advance of the due date of the last paid installment
   (DDLPI) between the two months. A delinquent loan pays 0 installments; a catch-up or a
   pay-ahead pays several. Without DDLPI, a missed payment followed by a catch-up reads as a
   negative and then a positive "curtailment".
2. **Servicing convention.** Under **no recast**, the US fixed-rate norm, the level payment
   stays the original ``A0`` after a curtailment, so later scheduled principal is ``A0 - I``.
   Under **recast** the payment is re-amortized on the current balance. Using the wrong one
   creates phantom curtailments every month after a real one. This is exactly the bias in the
   run-off decomposition's re-amortizing residual (RELIABILITY_PLAN A11).
3. **Disclosure precision.** Balances in the first six months are rounded to $1,000 for
   privacy, and reporting cycles changed in 2019-05 and 2025-10. Months whose balances may be
   rounded are excluded. Transition months are flagged. A dead band absorbs cent rounding.

:func:`estimate` returns the residual, the inferred curtailment and an eligibility mask with the
reason for every exclusion. The synthetic validation (``tests/unit/test_curtailment.py``) measures
precision and recall against known curtailments, including both conventions, rounding,
delinquency and pay-ahead. The decision rule for using the method on real data is in
``docs/validation/CURTAILMENTS.md``. Until that rule passes privately, the engine doesn't model
curtailments, and every CPR stays labeled full-payoff-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from prepay import periods
from prepay.arrays import BoolArray, FloatArray, IntArray
from prepay.features.machine import ObjectArray
from prepay.finance.amortization import level_payment

Convention = Literal["no_recast", "recast"]
ROUNDED_AGE_MAX = 6  # balances disclosed rounded to $1,000 through this loan age
DEAD_BAND_USD = 1.0
MAX_INSTALLMENTS = 12
#: Reporting-cycle changes (SOURCE_RESEARCH addendum): the first month of each new convention.
TRANSITION_MONTHS = (periods.month(2019, 5), periods.month(2025, 10))


@dataclass(frozen=True, slots=True)
class LoanMonths:
    """Consecutive observed months of loans: every array has one entry per (loan, month t).

    Balances are in USD; ``note_rate`` is a decimal per year; months are month indices.
    """

    balance_prev: FloatArray  # B_{t-1}
    balance: FloatArray  # B_t
    ddlpi_prev: IntArray  # due date of last paid installment at t-1 (-1 if missing)
    ddlpi: IntArray
    note_rate: FloatArray
    original_upb: FloatArray
    original_term: IntArray
    remaining_prev: IntArray  # contractual payments remaining at the start of month t
    age_prev: IntArray  # loan age at t-1
    month: IntArray  # t
    terminal: BoolArray  # zero-balance record at t
    modified: BoolArray  # modification flag at t-1 or t
    deferred: BoolArray  # payment deferral or non-interest-bearing UPB at t-1 or t


def scheduled_principal(
    balance: FloatArray,
    note_rate: FloatArray,
    installments: IntArray,
    remaining: IntArray,
    original_payment: FloatArray,
    convention: Convention,
) -> FloatArray:
    """Principal of ``installments`` regular payments starting from ``balance``.

    Under ``no_recast`` each payment is the original level payment; under ``recast`` it is
    re-amortized on the current balance over the remaining term before every installment.
    """
    b = np.asarray(balance, dtype=np.float64).copy()
    k = np.asarray(installments, dtype=np.int64)
    n = np.asarray(remaining, dtype=np.int64).copy()
    paid = np.zeros_like(b)
    for step in range(int(k.max(initial=0))):
        active = (k > step) & (b > 0) & (n > 0)
        interest = b * note_rate / 12.0
        payment = (
            original_payment
            if convention == "no_recast"
            else level_payment(b, note_rate, np.maximum(n, 1))
        )
        principal = np.where(n <= 1, b, np.clip(payment - interest, 0.0, b))
        principal = np.where(active, principal, 0.0)
        paid += principal
        b -= principal
        n = np.where(active, n - 1, n)
    return paid


@dataclass(frozen=True, slots=True)
class Estimate:
    installments: IntArray
    residual: FloatArray  # observed decline minus scheduled principal (USD)
    curtailment: FloatArray  # residual above the dead band on eligible months, else 0
    eligible: BoolArray
    exclusion: ObjectArray  # reason per row ("" when eligible)


def estimate(
    months: LoanMonths,
    *,
    convention: Convention = "no_recast",
    dead_band_usd: float = DEAD_BAND_USD,
) -> Estimate:
    """Residual and inferred curtailment per loan-month, with an explicit exclusion reason."""
    k = np.where(
        (months.ddlpi >= 0) & (months.ddlpi_prev >= 0), months.ddlpi - months.ddlpi_prev, -1
    )
    original_payment = level_payment(
        months.original_upb, months.note_rate, months.original_term.astype(np.float64)
    )
    scheduled = scheduled_principal(
        months.balance_prev,
        months.note_rate,
        np.clip(k, 0, MAX_INSTALLMENTS),
        months.remaining_prev,
        original_payment,
        convention,
    )
    residual = months.balance_prev - months.balance - scheduled
    reasons = np.full(k.shape[0], "", dtype=object)
    rules: tuple[tuple[np.ndarray, str], ...] = (
        (months.terminal, "terminal month"),
        (months.modified, "modified"),
        (months.deferred, "deferral or non-interest-bearing UPB"),
        ((months.ddlpi < 0) | (months.ddlpi_prev < 0), "no DDLPI"),
        ((k < 0) | (k > MAX_INSTALLMENTS), "implausible installment count"),
        (months.age_prev <= ROUNDED_AGE_MAX, "balance may be rounded to $1,000"),
        (np.isin(months.month, TRANSITION_MONTHS), "reporting-cycle transition"),
    )
    for mask, reason in rules:
        reasons = np.where((reasons == "") & np.asarray(mask, dtype=bool), reason, reasons)
    eligible = reasons == ""
    curtailment = np.where(eligible & (residual > dead_band_usd), residual, 0.0)
    return Estimate(k.astype(np.int64), residual, curtailment, eligible, reasons)


def summary(result: Estimate, balance_prev: FloatArray) -> dict[str, object]:
    """Aggregate diagnostics: eligibility, residual spread, and an implied curtailment SMM."""
    eligible = result.eligible
    one = eligible & (result.installments == 1)
    residual = result.residual[one]
    reasons, counts = np.unique(result.exclusion[~eligible].astype(str), return_counts=True)
    balance = float(balance_prev[eligible].sum())
    return {
        "rows": int(eligible.shape[0]),
        "eligible_share": float(eligible.mean()) if eligible.size else None,
        "exclusions": {str(r): int(c) for r, c in zip(reasons, counts, strict=True)},
        "one_installment_rows": int(one.sum()),
        "one_installment_residual_quantiles_usd": (
            {
                str(q): float(np.quantile(residual, q))
                for q in (0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99)
            }
            if residual.size
            else None
        ),
        "one_installment_within_dead_band_share": (
            float(np.mean(np.abs(residual) <= DEAD_BAND_USD)) if residual.size else None
        ),
        "negative_residual_share": (
            float(np.mean(result.residual[eligible] < -DEAD_BAND_USD)) if eligible.any() else None
        ),
        "curtailment_month_share": float(np.mean(result.curtailment[eligible] > 0))
        if eligible.any()
        else None,
        "implied_curtailment_smm": float(result.curtailment.sum() / balance) if balance else None,
    }


# --------------------------------------------------------------------------- private study
REGIMES = {
    "cycle_16th_to_15th": (0, TRANSITION_MONTHS[0] - 1),
    "calendar_month": (TRANSITION_MONTHS[0], TRANSITION_MONTHS[1] - 1),
    "calendar_plus_2_business_days": (TRANSITION_MONTHS[1], 10**6),
}
AGE_BUCKETS = {"7-12": (7, 12), "13-36": (13, 36), "37-120": (37, 120), "121+": (121, 10**6)}
#: CURTAILMENTS.md real-data rule (calendar-month regime, no-recast convention).
RULE_WITHIN_DEAD_BAND = 0.90
RULE_MAX_NEGATIVE = 0.05


def _yyyymm_index(column: str) -> str:
    return (
        f"case when regexp_full_match({column}, '[0-9]{{6}}') then "
        f"cast(substr({column}, 1, 4) as integer) * 12 + cast(substr({column}, 5, 2) as integer) "
        "- 1 end"
    )


def load_months(
    data_root: Path, *, through_month: int, sample_fraction: float | None
) -> LoanMonths:
    """Consecutive months of eligible loans: silver states plus DDLPI from bronze."""
    import duckdb

    from prepay.features.panel import sample_clause
    from prepay.transform import warehouse_path

    pattern = (data_root / "bronze" / "sflld" / "*" / "*" / "performance.parquet").as_posix()
    sample = sample_clause(sample_fraction)
    query = f"""
        with ddlpi as (
            select loan_id, {_yyyymm_index("period")} as period_month,
                   any_value({_yyyymm_index("ddlpi")}) as ddlpi_month
            from read_parquet('{pattern}', hive_partitioning = true)
            where {sample}
            group by all
        ),
        states as (
            select s.loan_id, s.period_month, s.current_upb, s.loan_age, s.zero_balance_code,
                   s.modification_flag, s.payment_deferral_flag, s.non_interest_bearing_upb,
                   d.ddlpi_month,
                   lag(s.current_upb) over w as upb_prev,
                   lag(s.period_month) over w as month_prev,
                   lag(d.ddlpi_month) over w as ddlpi_prev,
                   lag(s.loan_age) over w as age_prev,
                   lag(s.modification_flag) over w as modification_prev,
                   lag(s.payment_deferral_flag) over w as deferral_prev,
                   lag(s.non_interest_bearing_upb) over w as nib_prev
            from int_loan_month_state as s
            left join ddlpi as d using (loan_id, period_month)
            where {sample} and s.period_month <= $through
            window w as (partition by s.loan_id order by s.period_month)
        )
        select st.*, l.note_rate_pct, l.original_upb, l.original_loan_term, l.maturity_month
        from states as st
        inner join int_loans as l using (loan_id)
        where st.month_prev = st.period_month - 1 and st.upb_prev > 0
    """  # noqa: S608 - fixed identifiers; the sample clause comes from sample_clause()
    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
        table = con.sql(query, params={"through": through_month}).to_arrow_table()

    def num(name: str) -> FloatArray:
        return np.asarray(table[name].cast("double").to_numpy(zero_copy_only=False), np.float64)

    def present(name: str) -> BoolArray:
        values = table[name].to_pylist()
        return np.array([v is not None and v != "" for v in values], dtype=bool)

    def months_of(name: str) -> IntArray:
        values = num(name)
        return np.where(np.isfinite(values), values, -1).astype(np.int64)

    month = months_of("period_month")
    nib = np.nan_to_num(num("non_interest_bearing_upb")) + np.nan_to_num(num("nib_prev"))
    return LoanMonths(
        balance_prev=num("upb_prev"),
        balance=np.nan_to_num(num("current_upb")),
        ddlpi_prev=months_of("ddlpi_prev"),
        ddlpi=months_of("ddlpi_month"),
        note_rate=num("note_rate_pct") / 100.0,
        original_upb=num("original_upb"),
        original_term=months_of("original_loan_term"),
        remaining_prev=months_of("maturity_month") - month + 1,
        age_prev=months_of("age_prev"),
        month=month,
        terminal=present("zero_balance_code"),
        modified=present("modification_flag") | present("modification_prev"),
        deferred=present("payment_deferral_flag") | present("deferral_prev") | (nib > 0),
    )


def _subset(months: LoanMonths, mask: BoolArray) -> LoanMonths:
    return LoanMonths(**{name: getattr(months, name)[mask] for name in months.__slots__})


def study(
    data_root: Path,
    *,
    through_month: int,
    sample_fraction: float | None,
    synthetic: bool,
) -> dict[str, object]:
    """Aggregate feasibility report for both conventions, by reporting regime and age."""
    months = load_months(data_root, through_month=through_month, sample_fraction=sample_fraction)
    report: dict[str, object] = {
        "kind": "prepay-curtailment-study",
        "synthetic": synthetic,
        "through": periods.to_iso(through_month),
        "sample_fraction": sample_fraction,
        "rows": int(months.month.shape[0]),
        "dead_band_usd": DEAD_BAND_USD,
        "conventions": {},
    }
    conventions: dict[str, dict[str, dict[str, dict[str, object]]]] = {}
    conventions_order: tuple[Convention, ...] = ("no_recast", "recast")
    for convention in conventions_order:
        by_regime: dict[str, dict[str, object]] = {}
        for regime, (first, last) in REGIMES.items():
            mask = (months.month >= first) & (months.month <= last)
            if mask.any():
                subset = _subset(months, mask)
                result = estimate(subset, convention=convention)
                by_regime[regime] = summary(result, subset.balance_prev)
        by_age: dict[str, dict[str, object]] = {}
        for bucket, (low, high) in AGE_BUCKETS.items():
            mask = (months.age_prev >= low) & (months.age_prev <= high)
            if mask.any():
                subset = _subset(months, mask)
                result = estimate(subset, convention=convention)
                by_age[bucket] = summary(result, subset.balance_prev)
        conventions[convention] = {"by_reporting_regime": by_regime, "by_age_months": by_age}
    report["conventions"] = conventions
    calendar = conventions["no_recast"]["by_reporting_regime"].get("calendar_month", {})
    within = calendar.get("one_installment_within_dead_band_share")
    negative = calendar.get("negative_residual_share")
    report["decision"] = {
        "rule": f"no-recast, calendar-month regime: >= {RULE_WITHIN_DEAD_BAND:.0%} of "
        f"one-installment months within ${DEAD_BAND_USD:.0f}, and <= {RULE_MAX_NEGATIVE:.0%} "
        "negative residuals (docs/validation/CURTAILMENTS.md)",
        "within_dead_band_share": within,
        "negative_residual_share": negative,
        "defensible": isinstance(within, float)
        and isinstance(negative, float)
        and within >= RULE_WITHIN_DEAD_BAND
        and negative <= RULE_MAX_NEGATIVE,
    }
    return report
