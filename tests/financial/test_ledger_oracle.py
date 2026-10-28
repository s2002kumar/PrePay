"""Finance engine vs the independent Decimal oracle (FINANCIAL_CONVENTIONS §6).

Test names carry the §6 item number they evidence. Item 7 (market-rate shocks leave contractual
flows unchanged) needs the scenario layer and lives with it; item 9 is in ``test_replines.py`` and
item 10 in ``test_montecarlo.py``.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from prepay.finance import (
    CreditAssumptions,
    FinanceInputError,
    HazardPaths,
    InvalidHazardError,
    LoanLines,
    cash_wal_years,
    conservation_residuals,
    cpr_model,
    exposure_exit_wal_years,
    horizon_summary,
    project,
    psa_cpr,
    psa_smm,
)
from prepay.finance.amortization import contractual_balance_after, level_payment
from tests.financial.oracle import OracleLedger, oracle_line, oracle_payment

#: Engine-vs-oracle tolerance: one part in 1e9 of the line's initial balance (0.1 cent per $1M).
RTOL_OF_INITIAL = 1e-9
NO_CREDIT = CreditAssumptions(severity=0.0, recovery_lag_months=0)


def tol(initial: float) -> float:
    return RTOL_OF_INITIAL * max(initial, 1.0) + 1e-12


def single_line(balance: float, rate: float, remaining: int) -> LoanLines:
    return LoanLines.from_values([balance], [rate], [remaining])


def assert_line_matches_oracle(
    balance: float,
    rate: float,
    remaining: int,
    prepay: np.ndarray,
    credit: np.ndarray,
    assumptions: CreditAssumptions = NO_CREDIT,
) -> OracleLedger:
    months = prepay.shape[0]
    result = project(
        single_line(balance, rate, remaining),
        HazardPaths.from_prepay_credit(prepay[None, :], credit[None, :]),
        assumptions,
        months,
        keep_lines=True,
    )
    assert result.lines is not None
    oracle = oracle_line(
        balance,
        rate,
        remaining,
        prepay.tolist(),
        credit.tolist(),
        severity=assumptions.severity,
        recovery_lag_months=assumptions.recovery_lag_months,
    )
    bound = tol(balance)
    for k, month in enumerate(oracle.months):
        got = {
            "beginning": result.lines.beginning_upb[0, k],
            "interest": result.lines.contractual_interest_accrued[0, k],
            "scheduled": result.lines.scheduled_principal[0, k],
            "prepaid": result.lines.voluntary_prepay_principal[0, k],
            "disposed": result.lines.credit_exit_principal[0, k],
            "ending": result.lines.ending_upb[0, k],
        }
        for name, value in got.items():
            expected = float(getattr(month, name))
            assert abs(value - expected) <= bound, (name, k, value, expected)
    for k in range(months):
        expected_recovery = float(oracle.recoveries.get(k, Decimal(0)))
        assert abs(result.pool.recoveries_received[k] - expected_recovery) <= bound
        expected_loss = float(oracle.losses.get(k, Decimal(0)))
        assert abs(result.pool.illustrative_credit_loss[k] - expected_loss) <= bound
    return oracle


# ------------------------------------------------------------------ §6.1 360-month amortization


@pytest.mark.parametrize("rate", [0.0, 0.02, 0.06, 0.15])
def test_6_1_full_term_amortizes_to_zero_and_matches_oracle(rate: float) -> None:
    balance, term = 350_000.0, 360
    zeros = np.zeros(term)
    assert_line_matches_oracle(balance, rate, term, zeros, zeros)

    ledger = project(
        single_line(balance, rate, term), HazardPaths.constant(1, term, 0, 0), NO_CREDIT, term
    ).pool
    assert ledger.ending_upb[-1] == 0.0
    assert abs(ledger.scheduled_principal.sum() - balance) <= tol(balance)
    # A level-payment loan pays the same P+I every month.
    payment = ledger.scheduled_principal + ledger.contractual_interest_accrued
    expected_payment = float(oracle_payment(balance, rate, term))
    assert np.max(np.abs(payment - expected_payment)) <= tol(balance)


@pytest.mark.parametrize(
    ("balance", "rate", "term", "expected_cents"),
    [
        (200_000.0, 0.06, 360, 1199.10),  # textbook 30-year example
        (300_000.0, 0.07, 360, 1995.91),
        (100_000.0, 0.0, 360, 277.78),
        (150_000.0, 0.045, 180, 1147.49),
    ],
)
def test_6_1_known_payment_values(
    balance: float, rate: float, term: int, expected_cents: float
) -> None:
    payment = float(level_payment(balance, rate, term))
    assert round(payment, 2) == expected_cents
    assert abs(payment - float(oracle_payment(balance, rate, term))) <= tol(balance)


@pytest.mark.parametrize("rate", [0.0, 0.03, 0.0725])
def test_6_3_zero_hazards_follow_closed_form_balance(rate: float) -> None:
    balance, term = 425_000.0, 360
    ledger = project(
        single_line(balance, rate, term), HazardPaths.constant(1, term, 0, 0), NO_CREDIT, term
    ).pool
    for k in (1, 12, 60, 180, 359, 360):
        expected = contractual_balance_after(balance, rate, term, k)
        assert abs(ledger.ending_upb[k - 1] - expected) <= tol(balance)
    assert ledger.voluntary_prepay_principal.sum() == 0.0
    assert ledger.credit_exit_principal.sum() == 0.0


# ------------------------------------------------------------------ §6.2 edge cases


def test_6_2_single_remaining_payment_retires_balance_exactly() -> None:
    ledger = project(
        single_line(12_345.67, 0.065, 1), HazardPaths.constant(1, 3, 0, 0), NO_CREDIT, 3
    ).pool
    assert ledger.scheduled_principal[0] == 12_345.67
    assert ledger.contractual_interest_accrued[0] == pytest.approx(12_345.67 * 0.065 / 12)
    assert ledger.ending_upb.tolist() == [0.0, 0.0, 0.0]
    assert ledger.scheduled_principal[1:].tolist() == [0.0, 0.0]


@example(balance=987_654.32, rate=0.0799)  # unforced annuity math leaves 1.16e-10 here
@given(st.floats(0.01, 2e6), st.floats(0.0, 0.3))
def test_6_2_final_payment_leaves_exactly_zero(balance: float, rate: float) -> None:
    ledger = project(
        single_line(balance, rate, 1), HazardPaths.constant(1, 1, 0, 0), NO_CREDIT, 1
    ).pool
    assert ledger.scheduled_principal[0] == balance
    assert ledger.ending_upb[0] == 0.0


@pytest.mark.parametrize("rate", [1e-12, 1e-6, 0.15, 0.30])
def test_6_2_extreme_coupons_match_oracle(rate: float) -> None:
    zeros = np.zeros(360)
    assert_line_matches_oracle(275_000.0, rate, 360, zeros, zeros)


def test_6_2_tiny_coupon_converges_to_zero_rate_schedule() -> None:
    tiny = float(level_payment(360_000.0, 1e-12, 360))
    flat = float(level_payment(360_000.0, 0.0, 360))
    assert abs(tiny - flat) < 1e-6


@pytest.mark.parametrize("balance", [0.01, 0.99, 1.0])
def test_6_2_cent_balances_match_oracle(balance: float) -> None:
    zeros = np.zeros(360)
    assert_line_matches_oracle(balance, 0.05, 360, zeros, zeros)


def test_6_2_zero_balance_line_produces_zeros_not_nan() -> None:
    lines = LoanLines.from_values([0.0, 100_000.0], [0.05, 0.05], [0, 360])
    ledger = project(
        lines, HazardPaths.constant(2, 12, 0.01, 0.001), NO_CREDIT, 12, keep_lines=True
    )
    assert ledger.lines is not None
    for arr in (ledger.lines.scheduled_principal, ledger.lines.ending_upb):
        assert np.all(np.isfinite(arr))
        assert np.all(arr[0] == 0.0)


# ------------------------------------------------------------------ §6.4 degenerate hazards


def test_6_4_certain_payoff_returns_all_exposure_in_month_one() -> None:
    balance, rate = 250_000.0, 0.055
    prepay = np.zeros(24)
    prepay[0] = 1.0
    assert_line_matches_oracle(balance, rate, 360, prepay, np.zeros(24))
    ledger = project(
        single_line(balance, rate, 360),
        HazardPaths.from_prepay_credit(prepay[None, :], np.zeros((1, 24))),
        NO_CREDIT,
        24,
    ).pool
    first_scheduled = ledger.scheduled_principal[0]
    assert ledger.voluntary_prepay_principal[0] == pytest.approx(balance - first_scheduled)
    assert ledger.principal_cash[0] == pytest.approx(balance)
    assert np.all(ledger.ending_upb == 0.0)
    assert np.all(ledger.principal_cash[1:] == 0.0)


def test_6_4_certain_credit_exit_is_exposure_exit_not_cash() -> None:
    balance, rate = 250_000.0, 0.055
    credit = np.zeros(24)
    credit[0] = 1.0
    assumptions = CreditAssumptions(severity=0.4, recovery_lag_months=6)
    assert_line_matches_oracle(balance, rate, 360, np.zeros(24), credit, assumptions)
    ledger = project(
        single_line(balance, rate, 360),
        HazardPaths.from_prepay_credit(np.zeros((1, 24)), credit[None, :]),
        assumptions,
        24,
    ).pool
    exited = balance - ledger.scheduled_principal[0]
    assert ledger.credit_exit_principal[0] == pytest.approx(exited)
    assert ledger.voluntary_prepay_principal.sum() == 0.0
    # Month 1 cash is the scheduled payment only; the disposition is not received cash.
    assert ledger.principal_cash[0] == pytest.approx(ledger.scheduled_principal[0])
    assert ledger.recoveries_received[6] == pytest.approx(0.6 * exited)
    assert ledger.illustrative_credit_loss[6] == pytest.approx(0.4 * exited)
    assert ledger.principal_cash.sum() + ledger.illustrative_credit_loss.sum() == pytest.approx(
        balance
    )


# ------------------------------------------------------------------ §6.5 arbitrary simplex


@st.composite
def pools(draw: st.DrawFn) -> tuple[LoanLines, HazardPaths, CreditAssumptions, int]:
    count = draw(st.integers(1, 6))
    months = draw(st.integers(1, 96))
    seed = draw(st.integers(0, 2**32 - 1))
    rng = np.random.default_rng(seed)
    balance = rng.choice([0.0, 0.01, 1.0, 50_000.0, 999_999.99], size=count)
    balance = np.where(rng.random(count) < 0.5, rng.uniform(0, 2e6, count), balance)
    rate = rng.choice([0.0, 1e-9, 0.03, 0.07, 0.2], size=count)
    remaining = rng.integers(1, 481, size=count)
    u = rng.random((count, months))
    v = rng.random((count, months))
    extremes = rng.random((count, months))
    u = np.where(extremes < 0.05, 1.0, np.where(extremes > 0.95, 0.0, u))
    prepay = u * draw(st.sampled_from([1.0, 0.1, 0.01]))
    credit = (1.0 - prepay) * v * draw(st.sampled_from([1.0, 0.05, 0.0]))
    assumptions = CreditAssumptions(
        severity=draw(st.sampled_from([0.0, 0.35, 1.0])),
        recovery_lag_months=draw(st.integers(0, 30)),
    )
    lines = LoanLines.from_values(balance, rate, remaining)
    return lines, HazardPaths.from_prepay_credit(prepay, credit), assumptions, months


@given(pools())
def test_6_5_arbitrary_simplex_conserves_principal(
    case: tuple[LoanLines, HazardPaths, CreditAssumptions, int],
) -> None:
    lines, hazards, assumptions, months = case
    result = project(lines, hazards, assumptions, months, keep_lines=True)
    pool, detail = result.pool, result.lines
    assert detail is not None
    initial = float(lines.balance.sum())
    for arr in (
        detail.beginning_upb,
        detail.scheduled_principal,
        detail.ending_upb,
        detail.voluntary_prepay_principal,
        detail.credit_exit_principal,
    ):
        assert np.all(np.isfinite(arr))
        assert np.all(arr >= 0.0)
    # Per-line, per-month exposure identity.
    residual = detail.beginning_upb - (
        detail.scheduled_principal
        + detail.voluntary_prepay_principal
        + detail.credit_exit_principal
        + detail.ending_upb
    )
    assert np.max(np.abs(residual)) <= tol(initial)
    # No principal created: cash + losses + still-outstanding never exceeds the start.
    assert pool.principal_cash.sum() <= initial + tol(initial)
    assert conservation_residuals(pool).ok
    # Line 0 against the exact oracle.
    oracle = oracle_line(
        float(lines.balance[0]),
        float(lines.annual_rate[0]),
        int(lines.remaining_payments[0]),
        hazards.prepay[0].tolist(),
        hazards.credit[0].tolist(),
    )
    expected_ending = np.array([float(m.ending) for m in oracle.months])
    assert np.max(np.abs(detail.ending_upb[0] - expected_ending)) <= tol(float(lines.balance[0]))


# ------------------------------------------------------------------ §6.6 lag crossing horizon


def test_6_6_recoveries_beyond_horizon_are_carried_and_block_cash_wal() -> None:
    lines = single_line(300_000.0, 0.06, 360)
    assumptions = CreditAssumptions(severity=0.3, recovery_lag_months=12)
    short = project(lines, HazardPaths.constant(1, 24, 0.01, 0.002), assumptions, 24).pool
    assert short.pending_recoveries_after_horizon > 0.0
    assert short.pending_losses_after_horizon > 0.0
    assert cash_wal_years(short) is None
    assert exposure_exit_wal_years(short) is None
    summary = horizon_summary(short, 24)
    # Exits in months 13..24 resolve after month 24 and must be reported as pending.
    exits_unresolved = short.credit_exit_principal[12:24].sum()
    assert summary.pending_recoveries == pytest.approx(0.7 * exits_unresolved)
    assert summary.pending_losses == pytest.approx(0.3 * exits_unresolved)

    full = project(lines, HazardPaths.constant(1, 372, 0.01, 0.002), assumptions, 372).pool
    assert full.pending_recoveries_after_horizon == 0.0
    assert full.ending_upb[-1] == 0.0
    cash_wal, exit_wal = cash_wal_years(full), exposure_exit_wal_years(full)
    assert cash_wal is not None
    assert exit_wal is not None
    assert cash_wal > exit_wal  # lagged recoveries arrive later than the exposure exits


def test_6_6_horizon_summary_pending_matches_oracle() -> None:
    assumptions = CreditAssumptions(severity=0.25, recovery_lag_months=9)
    prepay, credit = np.full(36, 0.008), np.full(36, 0.004)
    oracle = assert_line_matches_oracle(200_000.0, 0.05, 360, prepay, credit, assumptions)
    pool = project(
        single_line(200_000.0, 0.05, 360),
        HazardPaths.from_prepay_credit(prepay[None, :], credit[None, :]),
        assumptions,
        36,
    ).pool
    summary = horizon_summary(pool, 20)
    due_later = sum(float(v) for k, v in oracle.recoveries.items() if k >= 20)
    exits_after = sum(float(m.disposed) for m in oracle.months[20:]) * 0.75
    assert summary.pending_recoveries == pytest.approx(due_later - exits_after, abs=1e-6)


# ------------------------------------------------------------------ §6.8 local monotonicity


@given(st.integers(0, 59), st.floats(0.0, 0.99), st.integers(0, 2**32 - 1))
def test_6_8_lower_payoff_hazard_lowers_same_month_payoff(
    month: int, shrink: float, seed: int
) -> None:
    rng = np.random.default_rng(seed)
    lines = LoanLines.from_values(
        rng.uniform(1e4, 1e6, 5), rng.uniform(0.02, 0.09, 5), rng.integers(120, 361, 5)
    )
    prepay = rng.uniform(0, 0.05, (5, 60))
    credit = rng.uniform(0, 0.005, (5, 60))
    lowered = prepay.copy()
    lowered[:, month] *= shrink
    base = project(lines, HazardPaths.from_prepay_credit(prepay, credit), NO_CREDIT, 60).pool
    alt = project(lines, HazardPaths.from_prepay_credit(lowered, credit), NO_CREDIT, 60).pool
    assert alt.voluntary_prepay_principal[month] <= base.voluntary_prepay_principal[month]
    np.testing.assert_array_equal(
        alt.voluntary_prepay_principal[:month], base.voluntary_prepay_principal[:month]
    )
    if base.voluntary_prepay_principal[month] > 0.0:
        assert alt.voluntary_prepay_principal[month] < base.voluntary_prepay_principal[month]


# ------------------------------------------------------------------ §6.11 PSA round trip


@pytest.mark.parametrize("speed", [0.5, 1.0, 2.5])
def test_6_11_psa_hazards_reproduce_psa_cpr(speed: float) -> None:
    months, start_age = 120, 0
    ages = np.arange(start_age + 1, start_age + months + 1)
    prepay = psa_smm(ages, speed)[None, :]
    ledger = project(
        single_line(500_000.0, 0.065, 360),
        HazardPaths.from_prepay_credit(prepay, np.zeros_like(prepay)),
        NO_CREDIT,
        months,
    ).pool
    np.testing.assert_allclose(cpr_model(ledger), psa_cpr(ages, speed), rtol=0, atol=1e-12)


# ------------------------------------------------------------------ §6.12 no rounding/clipping


def test_6_12_monetary_values_are_not_rounded() -> None:
    ledger = project(
        single_line(100_000.123456, 0.0611, 360), HazardPaths.constant(1, 2, 0, 0), NO_CREDIT, 2
    ).pool
    assert ledger.beginning_upb[0] == 100_000.123456
    cents = ledger.scheduled_principal[0] * 100
    assert cents != round(cents)


@pytest.mark.parametrize(
    ("prepay", "credit"),
    [(0.7, 0.4), (-0.01, 0.0), (0.0, -1e-6), (float("nan"), 0.0), (1.0 + 1e-6, 0.0)],
)
def test_6_12_invalid_hazards_are_rejected_not_clipped(prepay: float, credit: float) -> None:
    with pytest.raises(InvalidHazardError):
        project(
            single_line(1e5, 0.05, 360), HazardPaths.constant(1, 3, prepay, credit), NO_CREDIT, 3
        )


def test_6_12_explicit_active_must_complete_the_simplex() -> None:
    bad = HazardPaths(
        prepay=np.full((1, 3), 0.1), credit=np.full((1, 3), 0.1), active=np.full((1, 3), 0.7)
    )
    with pytest.raises(InvalidHazardError, match="sum to 1"):
        project(single_line(1e5, 0.05, 360), bad, NO_CREDIT, 3)


def test_hazard_shape_must_match_lines_and_horizon() -> None:
    with pytest.raises(InvalidHazardError, match="shape"):
        project(single_line(1e5, 0.05, 360), HazardPaths.constant(2, 3, 0.0, 0.0), NO_CREDIT, 3)


@pytest.mark.parametrize(
    ("balance", "rate", "remaining", "message"),
    [
        (-1.0, 0.05, 360, "non-negative"),
        (1e5, 1.5, 360, "annual_rate"),
        (1e5, -0.01, 360, "annual_rate"),
        (1e5, 0.05, 0, "remaining_payments"),
        (float("inf"), 0.05, 360, "finite"),
    ],
)
def test_invalid_loan_terms_are_rejected(
    balance: float, rate: float, remaining: int, message: str
) -> None:
    with pytest.raises(FinanceInputError, match=message):
        LoanLines.from_values([balance], [rate], [remaining])


@pytest.mark.parametrize(
    ("assumptions", "horizon"),
    [
        (CreditAssumptions(severity=1.5, recovery_lag_months=0), 12),
        (CreditAssumptions(severity=0.3, recovery_lag_months=-1), 12),
        (NO_CREDIT, 0),
        (NO_CREDIT, 601),
    ],
)
def test_invalid_assumptions_and_horizons_are_rejected(
    assumptions: CreditAssumptions, horizon: int
) -> None:
    with pytest.raises(FinanceInputError):
        project(
            single_line(1e5, 0.05, 360),
            HazardPaths.constant(1, max(horizon, 1), 0, 0),
            assumptions,
            horizon,
        )


def test_mismatched_line_arrays_are_rejected() -> None:
    with pytest.raises(FinanceInputError, match="equal length"):
        LoanLines.from_values([1e5, 2e5], [0.05], [360, 360])
