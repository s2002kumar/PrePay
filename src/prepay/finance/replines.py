"""Representative-line (rep-line) aggregation and its measured approximation error.

A rep line replaces a group of loans with one line carrying the group's total balance, its
balance-weighted coupon (WAC), balance-weighted remaining term (WAM, rounded to whole months) and
balance-weighted hazard paths. This is an *approximation*; FINANCIAL_CONVENTIONS §2 requires its
error against exact loan-level projection to be measured and disclosed, never assumed away.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from prepay.finance.amortization import FloatArray, IntArray
from prepay.finance.ledger import CreditAssumptions, HazardPaths, LoanLines, project
from prepay.finance.metrics import cash_wal_years, horizon_summary


def bucket_labels(
    lines: LoanLines, *, rate_step: float = 0.0025, term_step_months: int = 12
) -> IntArray:
    """Group lines by note-rate bucket (``rate_step`` wide) and remaining-term bucket."""
    if rate_step <= 0 or term_step_months <= 0:
        raise ValueError("bucket widths must be positive")
    rate_bucket = np.floor(lines.annual_rate / rate_step).astype(np.int64)
    term_bucket = (lines.remaining_payments // term_step_months).astype(np.int64)
    _, labels = np.unique(np.stack([rate_bucket, term_bucket], axis=1), axis=0, return_inverse=True)
    return np.asarray(labels.reshape(-1), dtype=np.int64)


def aggregate(
    lines: LoanLines, hazards: HazardPaths, labels: npt.ArrayLike
) -> tuple[LoanLines, HazardPaths]:
    """Collapse lines sharing a label into balance-weighted rep lines."""
    groups = np.asarray(labels, dtype=np.int64)
    if groups.shape != (lines.count,):
        raise ValueError("labels must have one entry per line")
    ids = np.unique(groups)
    balance = np.zeros(ids.size)
    rate = np.zeros(ids.size)
    remaining = np.zeros(ids.size, dtype=np.int64)
    months = hazards.shape[1]
    prepay = np.zeros((ids.size, months))
    credit = np.zeros((ids.size, months))
    for row, group in enumerate(ids):
        member = groups == group
        weights = lines.balance[member]
        total = float(weights.sum())
        balance[row] = total
        if total <= 0.0:
            weights = np.ones_like(weights)
            total = float(weights.size)
        w = weights / total
        rate[row] = float(w @ lines.annual_rate[member])
        remaining[row] = round(float(w @ lines.remaining_payments[member]))
        prepay[row] = w @ hazards.prepay[member]
        credit[row] = w @ hazards.credit[member]
    rep_lines = LoanLines.from_values(balance, rate, remaining)
    return rep_lines, HazardPaths.from_prepay_credit(prepay, credit)


@dataclass(frozen=True, slots=True)
class RepLineError:
    """Rep-line minus loan-level error for one pool profile."""

    rep_lines: int
    loan_lines: int
    max_abs_ending_upb_error_fraction: float  # max_t |dB_t| / initial UPB
    cash_wal_error_months: float | None
    principal_returned_12m_error_pp: float  # percentage points of initial UPB
    principal_returned_24m_error_pp: float
    interest_accrued_error_fraction: float  # |d sum I| / sum I (loan-level)


def measure_error(
    lines: LoanLines,
    hazards: HazardPaths,
    credit: CreditAssumptions,
    horizon_months: int,
    labels: npt.ArrayLike,
) -> RepLineError:
    """Project both representations over the same horizon and report the differences."""
    exact = project(lines, hazards, credit, horizon_months).pool
    rep_lines, rep_hazards = aggregate(lines, hazards, labels)
    approx = project(rep_lines, rep_hazards, credit, horizon_months).pool
    initial = exact.initial_upb

    wal_exact = cash_wal_years(exact)
    wal_approx = cash_wal_years(approx)
    wal_error = (
        (wal_approx - wal_exact) * 12.0
        if wal_exact is not None and wal_approx is not None
        else None
    )

    def returned_pp(months: int) -> float:
        m = min(months, horizon_months)
        delta = (
            horizon_summary(approx, m).principal_returned_fraction
            - horizon_summary(exact, m).principal_returned_fraction
        )
        return 100.0 * delta

    interest_exact = float(exact.contractual_interest_accrued.sum())
    interest_delta = abs(float(approx.contractual_interest_accrued.sum()) - interest_exact)
    ending_error: FloatArray = np.abs(approx.ending_upb - exact.ending_upb)
    return RepLineError(
        rep_lines=rep_lines.count,
        loan_lines=lines.count,
        max_abs_ending_upb_error_fraction=float(ending_error.max() / initial) if initial else 0.0,
        cash_wal_error_months=wal_error,
        principal_returned_12m_error_pp=returned_pp(12),
        principal_returned_24m_error_pp=returned_pp(24),
        interest_accrued_error_fraction=interest_delta / interest_exact if interest_exact else 0.0,
    )
