"""Rate conversions, PSA benchmark and WAL/horizon metrics against analytical values."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from prepay.finance import (
    CreditAssumptions,
    HazardPaths,
    LoanLines,
    cash_wal_years,
    cpr_from_smm,
    credit_exit_rate,
    exposure_exit_wal_years,
    horizon_summary,
    project,
    psa_cpr,
    smm_from_cpr,
    smm_model,
)

NO_CREDIT = CreditAssumptions(severity=0.0, recovery_lag_months=0)


@given(st.floats(0.0, 1.0, allow_subnormal=False))
def test_cpr_smm_round_trip(cpr: float) -> None:
    assert float(cpr_from_smm(smm_from_cpr(cpr))) == pytest.approx(cpr, abs=1e-12)


def test_smm_of_six_percent_cpr() -> None:
    # 1 - 0.94 ** (1/12) = 0.0051430...
    assert float(smm_from_cpr(0.06)) == pytest.approx(0.005143, abs=1e-6)


@pytest.mark.parametrize(
    ("age", "cpr"), [(0, 0.0), (1, 0.002), (15, 0.03), (30, 0.06), (31, 0.06), (360, 0.06)]
)
def test_psa_ramp_and_plateau(age: int, cpr: float) -> None:
    assert float(psa_cpr(age)) == pytest.approx(cpr)
    assert float(psa_cpr(age, speed=2.0)) == pytest.approx(2 * cpr)


@pytest.mark.parametrize("bad", [-0.1, 1.1])
def test_rate_conversions_reject_out_of_range(bad: float) -> None:
    with pytest.raises(ValueError, match="CPR"):
        smm_from_cpr(bad)
    with pytest.raises(ValueError, match="SMM"):
        cpr_from_smm(bad)


def test_psa_rejects_impossible_speed() -> None:
    with pytest.raises(ValueError, match="above 100%"):
        psa_cpr(30, speed=20.0)


def test_cash_wal_analytical_zero_coupon_twelve_months() -> None:
    # $1,200 at 0% over 12 months returns $100/month: WAL = sum(t/12 * 100) / 1200 = 6.5/12 yr.
    ledger = project(
        LoanLines.from_values([1200.0], [0.0], [12]),
        HazardPaths.constant(1, 12, 0, 0),
        NO_CREDIT,
        12,
    ).pool
    assert cash_wal_years(ledger) == pytest.approx(6.5 / 12)
    assert exposure_exit_wal_years(ledger) == pytest.approx(6.5 / 12)


def test_cash_wal_equals_exit_wal_without_recovery_lag_or_severity() -> None:
    lines = LoanLines.from_values([300_000.0, 120_000.0], [0.05, 0.04], [360, 240])
    ledger = project(lines, HazardPaths.constant(2, 360, 0.01, 0.001), NO_CREDIT, 360).pool
    assert cash_wal_years(ledger) == pytest.approx(exposure_exit_wal_years(ledger))


def test_undefined_rates_are_nan_not_zero() -> None:
    ledger = project(
        LoanLines.from_values([1000.0], [0.05], [2]),
        HazardPaths.constant(1, 4, 0.1, 0.0),
        NO_CREDIT,
        4,
    ).pool
    smm = smm_model(ledger)
    assert np.isfinite(smm[0])
    assert np.all(np.isnan(smm[2:]))
    assert np.all(np.isnan(credit_exit_rate(ledger)[2:]))


def test_horizon_summary_totals_and_bounds() -> None:
    lines = LoanLines.from_values([250_000.0], [0.06], [360])
    assumptions = CreditAssumptions(severity=0.4, recovery_lag_months=3)
    ledger = project(lines, HazardPaths.constant(1, 60, 0.02, 0.003), assumptions, 60).pool
    summary = horizon_summary(ledger, 24)
    assert summary.principal_cash_received == pytest.approx(
        summary.scheduled_principal
        + summary.voluntary_prepay_principal
        + summary.recoveries_received
    )
    total = (
        summary.principal_cash_received
        + summary.illustrative_credit_loss
        + summary.ending_upb
        + summary.pending_recoveries
        + summary.pending_losses
    )
    assert total == pytest.approx(250_000.0)
    assert 0.0 < summary.principal_returned_fraction < 1.0
    with pytest.raises(ValueError, match="months"):
        horizon_summary(ledger, 61)
