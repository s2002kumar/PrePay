"""Second, exact oracle for the finance engine (R2 independent-oracle audit).

Built from the text of FINANCIAL_CONVENTIONS §2 and §5 with ``fractions.Fraction``:

- no rounding at any step;
- float inputs converted exactly;
- the annuity factor taken as an exact rational power.

The Decimal oracle (``oracle.py``) uses 60-digit arithmetic and was written alongside the engine.
This one shares neither its code nor its arithmetic. If the float engine agrees with an exact
answer, neither the engine nor the Decimal oracle is hiding a precision artifact. It also
checks the identities §2 states **exactly**, and the partial-principal installment arithmetic of
``prepay.evaluation.curtailment``.
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import pytest

from prepay.evaluation.curtailment import scheduled_principal
from prepay.finance import (
    CreditAssumptions,
    HazardPaths,
    LoanLines,
    cash_wal_years,
    exposure_exit_wal_years,
    project,
)
from prepay.finance.amortization import level_payment

ZERO = Fraction(0)


def payment(balance: Fraction, annual_rate: Fraction, n: int) -> Fraction:
    """§2: ``A = B i / (1 - (1+i)^-n)``, ``i = c/12``; ``A = B/n`` at a zero rate."""
    i = annual_rate / 12
    if i == 0:
        return balance / n
    growth = (1 + i) ** n
    return balance * i * growth / (growth - 1)


@dataclass
class ExactLedger:
    beginning: list[Fraction]
    interest: list[Fraction]
    scheduled: list[Fraction]
    prepaid: list[Fraction]
    disposed: list[Fraction]
    ending: list[Fraction]
    recoveries: dict[int, Fraction]
    losses: dict[int, Fraction]
    pending_recoveries: Fraction
    pending_losses: Fraction


def exact_ledger(
    balance: float,
    rate: float,
    remaining: int,
    prepay: list[float],
    credit: list[float],
    severity: float,
    lag: int,
) -> ExactLedger:
    """§2 month by month, exactly: scheduled principal before same-month exits."""
    b, c, sev = Fraction(balance), Fraction(rate), Fraction(severity)
    months = len(prepay)
    out = ExactLedger(
        [],
        [],
        [],
        [],
        [],
        [],
        collections.defaultdict(Fraction),
        collections.defaultdict(Fraction),
        ZERO,
        ZERO,
    )
    for k in range(months):
        n = remaining - k
        interest = b * c / 12
        if b == 0 or n <= 0:
            scheduled = ZERO
        elif n == 1:
            scheduled = b  # the final contractual month retires the balance
        else:
            scheduled = min(b, max(ZERO, payment(b, c, n) - interest))
        after = b - scheduled
        prepaid = Fraction(prepay[k]) * after
        disposed = Fraction(credit[k]) * after
        ending = after - prepaid - disposed
        for name, value in (
            ("beginning", b),
            ("interest", interest),
            ("scheduled", scheduled),
            ("prepaid", prepaid),
            ("disposed", disposed),
            ("ending", ending),
        ):
            getattr(out, name).append(value)
        if k + lag < months:
            out.recoveries[k + lag] += (1 - sev) * disposed
            out.losses[k + lag] += sev * disposed
        else:
            out.pending_recoveries += (1 - sev) * disposed
            out.pending_losses += sev * disposed
        b = ending
    return out


def _engine(
    balance: float,
    rate: float,
    remaining: int,
    prepay: np.ndarray,
    credit: np.ndarray,
    severity: float,
    lag: int,
):  # type: ignore[no-untyped-def]
    return project(
        LoanLines.from_values([balance], [rate], [remaining]),
        HazardPaths.from_prepay_credit(prepay[None, :], credit[None, :]),
        CreditAssumptions(severity=severity, recovery_lag_months=lag),
        prepay.shape[0],
    ).pool


def _close(engine: np.ndarray, exact: list[Fraction], scale: float) -> None:
    np.testing.assert_allclose(engine, [float(x) for x in exact], rtol=0, atol=1e-9 * scale)


@pytest.mark.parametrize("rate", [0.0, 0.02, 0.06, 0.15])
def test_360_month_amortization_retires_the_balance_exactly(rate: float) -> None:
    balance, months = 200_000.0, 360
    exact = exact_ledger(balance, rate, months, [0.0] * months, [0.0] * months, 0.0, 0)
    assert exact.ending[-1] == 0  # exactly zero in rational arithmetic
    assert sum(exact.scheduled) == Fraction(balance)
    pool = _engine(balance, rate, months, np.zeros(months), np.zeros(months), 0.0, 0)
    _close(pool.scheduled_principal, exact.scheduled, balance)
    _close(pool.contractual_interest_accrued, exact.interest, balance)
    _close(pool.ending_upb, exact.ending, balance)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_engine_matches_the_exact_ledger_with_competing_exits(seed: int) -> None:
    rng = np.random.default_rng(seed)
    months, balance, rate = 120, float(rng.uniform(5e4, 9e5)), float(rng.choice([0.031, 0.0725]))
    prepay = rng.uniform(0.0, 0.08, months)
    credit = rng.uniform(0.0, 0.004, months)
    severity, lag = 0.35, 7
    exact = exact_ledger(balance, rate, 300, list(prepay), list(credit), severity, lag)
    pool = _engine(balance, rate, 300, prepay, credit, severity, lag)
    _close(pool.beginning_upb, exact.beginning, balance)
    _close(pool.scheduled_principal, exact.scheduled, balance)
    _close(pool.voluntary_prepay_principal, exact.prepaid, balance)
    _close(pool.credit_exit_principal, exact.disposed, balance)
    _close(pool.ending_upb, exact.ending, balance)
    recoveries = [exact.recoveries.get(k, ZERO) for k in range(months)]
    losses = [exact.losses.get(k, ZERO) for k in range(months)]
    _close(pool.recoveries_received, recoveries, balance)
    _close(pool.illustrative_credit_loss, losses, balance)
    assert pool.pending_recoveries_after_horizon == pytest.approx(
        float(exact.pending_recoveries), abs=1e-9 * balance
    )
    # §2 identity, exactly: B_t = SP_t + PP_t + DC_t + B_{t+1}, every month.
    for k in range(months):
        assert exact.beginning[k] == (
            exact.scheduled[k] + exact.prepaid[k] + exact.disposed[k] + exact.ending[k]
        )
    # Cash ledger: a disposed dollar is either recovered or lost, never both.
    assert sum(exact.disposed) == (
        sum(exact.recoveries.values())
        + sum(exact.losses.values())
        + exact.pending_recoveries
        + exact.pending_losses
    )


def test_wal_definitions_match_their_exact_formulas() -> None:
    """§5: cash WAL weights SP + PP + RC by t/12 (t = 1, 2, ...); exposure WAL uses SP + PP + DC."""
    months, balance, rate = 360 + 6, 150_000.0, 0.05
    rng = np.random.default_rng(9)
    prepay = np.concatenate([rng.uniform(0.0, 0.03, 360), np.zeros(6)])
    credit = np.concatenate([rng.uniform(0.0, 0.002, 360), np.zeros(6)])
    exact = exact_ledger(balance, rate, 360, list(prepay), list(credit), 0.4, 6)
    cash = [
        exact.scheduled[k] + exact.prepaid[k] + exact.recoveries.get(k, ZERO) for k in range(months)
    ]
    exits = [exact.scheduled[k] + exact.prepaid[k] + exact.disposed[k] for k in range(months)]
    cash_wal = sum(Fraction(k + 1, 12) * x for k, x in enumerate(cash)) / sum(cash)
    exit_wal = sum(Fraction(k + 1, 12) * x for k, x in enumerate(exits)) / sum(exits)
    pool = _engine(balance, rate, 360, prepay, credit, 0.4, 6)
    assert cash_wal_years(pool) == pytest.approx(float(cash_wal), rel=1e-12)
    assert exposure_exit_wal_years(pool) == pytest.approx(float(exit_wal), rel=1e-12)


@pytest.mark.parametrize("installments", [0, 1, 2, 3])
def test_partial_principal_installments_match_the_exact_schedule(installments: int) -> None:
    """Curtailment estimator: principal of k regular payments under both servicing conventions."""
    balance, rate, remaining, original = 187_431.27, 0.0475, 301, 210_000.0
    original_payment = Fraction(float(level_payment(original, rate, 360.0)))
    for convention in ("no_recast", "recast"):
        b, n, paid = Fraction(balance), remaining, ZERO
        for _ in range(installments):
            interest = b * Fraction(rate) / 12
            due = original_payment if convention == "no_recast" else payment(b, Fraction(rate), n)
            principal = b if n <= 1 else min(b, max(ZERO, due - interest))
            paid += principal
            b -= principal
            n -= 1
        engine = scheduled_principal(
            np.array([balance]),
            np.array([rate]),
            np.array([installments]),
            np.array([remaining]),
            np.array([float(original_payment)]),
            convention,  # type: ignore[arg-type]
        )
        assert engine[0] == pytest.approx(float(paid), abs=1e-9)
