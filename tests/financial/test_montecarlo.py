"""§6.10: seeded Monte Carlo means converge to the deterministic expected ledger."""

from __future__ import annotations

import numpy as np
import pytest

from prepay.finance import CreditAssumptions, FinanceInputError, HazardPaths, LoanLines, project
from prepay.finance.montecarlo import INTERVAL_KIND, simulate


def heterogeneous_pool(seed: int, count: int = 40) -> LoanLines:
    rng = np.random.default_rng(seed)
    return LoanLines.from_values(
        rng.uniform(80_000, 650_000, count),
        rng.uniform(0.025, 0.08, count),
        rng.integers(150, 361, count),
    )


def test_6_10_monte_carlo_mean_converges_to_expected_ledger() -> None:
    lines = heterogeneous_pool(11)
    months = 48
    rng = np.random.default_rng(5)
    hazards = HazardPaths.from_prepay_credit(
        rng.uniform(0.005, 0.04, (lines.count, months)),
        rng.uniform(0.0, 0.004, (lines.count, months)),
    )
    assumptions = CreditAssumptions(severity=0.3, recovery_lag_months=6)
    expected = project(lines, hazards, assumptions, months).pool
    sim = simulate(lines, hazards, assumptions, months, paths=4000, seed=20261028)
    assert sim.interval_kind == INTERVAL_KIND == "monte_carlo_sampling"
    pairs = [
        (sim.scheduled_principal_mean, sim.scheduled_principal_se, expected.scheduled_principal),
        (
            sim.voluntary_prepay_principal_mean,
            sim.voluntary_prepay_principal_se,
            expected.voluntary_prepay_principal,
        ),
        (
            sim.credit_exit_principal_mean,
            sim.credit_exit_principal_se,
            expected.credit_exit_principal,
        ),
        (sim.ending_upb_mean, sim.ending_upb_se, expected.ending_upb),
    ]
    for mean, se, target in pairs:
        z = np.abs(mean - target) / np.maximum(se, 1e-9)
        assert np.all(z < 5.0), float(z.max())


def test_monte_carlo_is_reproducible_for_a_seed() -> None:
    lines = heterogeneous_pool(3, count=10)
    hazards = HazardPaths.constant(10, 12, 0.03, 0.002)
    assumptions = CreditAssumptions(severity=0.3, recovery_lag_months=0)
    a = simulate(lines, hazards, assumptions, 12, paths=50, seed=1)
    b = simulate(lines, hazards, assumptions, 12, paths=50, seed=1)
    c = simulate(lines, hazards, assumptions, 12, paths=50, seed=2)
    np.testing.assert_array_equal(a.ending_upb_mean, b.ending_upb_mean)
    assert not np.array_equal(a.ending_upb_mean, c.ending_upb_mean)


def test_monte_carlo_rejects_too_few_paths() -> None:
    lines = heterogeneous_pool(3, count=2)
    with pytest.raises(FinanceInputError):
        simulate(
            lines,
            HazardPaths.constant(2, 3, 0, 0),
            CreditAssumptions(severity=0.0, recovery_lag_months=0),
            3,
            paths=1,
            seed=0,
        )
