"""§6.9: rep-line approximation measured against exact loan-level projection.

Rep lines are exact for homogeneous groups and only approximate otherwise; the size of the error
is measured here on six deliberately different synthetic pool profiles.
"""

from __future__ import annotations

import numpy as np
import pytest

from prepay.finance import CreditAssumptions, HazardPaths, LoanLines
from prepay.finance.replines import aggregate, bucket_labels, measure_error

MONTHS = 372
CREDIT = CreditAssumptions(severity=0.35, recovery_lag_months=12)


def profile(name: str, count: int = 300) -> tuple[LoanLines, HazardPaths]:
    rng = np.random.default_rng(sum(name.encode()))
    if name == "homogeneous":
        lines = LoanLines.from_values(
            np.full(count, 250_000.0), np.full(count, 0.06), np.full(count, 360)
        )
        return lines, HazardPaths.constant(count, MONTHS, 0.01, 0.0005)
    if name == "coupon_dispersion":
        rate = rng.uniform(0.025, 0.085, count)
        remaining = np.full(count, 360)
    elif name == "mixed_terms":
        rate = rng.uniform(0.04, 0.06, count)
        remaining = rng.choice([180, 360], size=count)
    elif name == "mixed_seasoning":
        rate = rng.uniform(0.03, 0.07, count)
        remaining = rng.integers(60, 361, count)
    elif name in ("heterogeneous_speeds", "credit_heavy"):
        rate = rng.uniform(0.05, 0.055, count)
        remaining = np.full(count, 360)
    else:
        raise ValueError(name)
    balance = rng.uniform(60_000, 900_000, count)
    lines = LoanLines.from_values(balance, rate, remaining)
    if name == "heterogeneous_speeds":
        speed = rng.choice([0.002, 0.04], size=count)  # fast and slow borrowers mixed
        prepay = np.repeat(speed[:, None], MONTHS, axis=1)
        credit = np.full((count, MONTHS), 0.0003)
    elif name == "credit_heavy":
        prepay = np.full((count, MONTHS), 0.006)
        credit = np.repeat(rng.uniform(0.0, 0.01, count)[:, None], MONTHS, axis=1)
    else:
        # Refinance incentive: higher coupons prepay faster.
        prepay = np.repeat((0.002 + 0.6 * np.maximum(rate - 0.035, 0.0))[:, None], MONTHS, axis=1)
        credit = np.full((count, MONTHS), 0.0004)
    return lines, HazardPaths.from_prepay_credit(prepay, credit)


PROFILES = [
    "homogeneous",
    "coupon_dispersion",
    "mixed_terms",
    "mixed_seasoning",
    "heterogeneous_speeds",
    "credit_heavy",
]


def test_6_9_homogeneous_group_is_exact() -> None:
    lines, hazards = profile("homogeneous")
    error = measure_error(lines, hazards, CREDIT, MONTHS, np.zeros(lines.count, dtype=np.int64))
    assert error.rep_lines == 1
    assert error.max_abs_ending_upb_error_fraction < 1e-12
    assert error.cash_wal_error_months is not None
    assert abs(error.cash_wal_error_months) < 1e-9


@pytest.mark.parametrize("name", PROFILES[1:])
def test_6_9_rep_line_error_is_measured_and_finite(name: str) -> None:
    lines, hazards = profile(name)
    labels = bucket_labels(lines)
    error = measure_error(lines, hazards, CREDIT, MONTHS, labels)
    assert error.rep_lines < error.loan_lines
    assert error.cash_wal_error_months is not None
    for value in (
        error.max_abs_ending_upb_error_fraction,
        error.cash_wal_error_months,
        error.principal_returned_12m_error_pp,
        error.principal_returned_24m_error_pp,
        error.interest_accrued_error_fraction,
    ):
        assert np.isfinite(value)


def test_6_9_hazard_heterogeneity_creates_real_aggregation_bias() -> None:
    """Averaging fast and slow borrowers ignores burnout-style composition change."""
    lines, hazards = profile("heterogeneous_speeds")
    error = measure_error(lines, hazards, CREDIT, MONTHS, np.zeros(lines.count, dtype=np.int64))
    # A single rep line with averaged hazards keeps prepaying fast after the fast borrowers have
    # gone, so it returns principal too early: a negative WAL error (too short) is expected.
    assert error.cash_wal_error_months is not None
    assert error.cash_wal_error_months < -1.0
    assert error.max_abs_ending_upb_error_fraction > 0.01


def test_aggregate_preserves_total_balance_and_simplex() -> None:
    lines, hazards = profile("mixed_seasoning")
    rep_lines, rep_hazards = aggregate(lines, hazards, bucket_labels(lines))
    assert rep_lines.balance.sum() == pytest.approx(lines.balance.sum())
    rep_hazards.validate(rep_lines.count, MONTHS)
