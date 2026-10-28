"""§6.9: rep-line approximation measured against exact loan-level projection.

Rep lines are exact for homogeneous groups and only approximate otherwise; the size of the error
is measured here on six deliberately different synthetic pool profiles.
"""

from __future__ import annotations

import numpy as np
import pytest

from prepay.finance.replines import aggregate, bucket_labels, measure_error
from prepay.finance.validation import (
    PROFILE_CREDIT,
    PROFILE_MONTHS,
    PROFILES,
    profile,
    render_report,
)

MONTHS = PROFILE_MONTHS
CREDIT = PROFILE_CREDIT


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


def test_disclosure_report_renders_every_profile() -> None:
    report = render_report()
    for name in PROFILES:
        assert f"| {name} |" in report
    assert "Monte Carlo" in report
