"""F1: synthetic validation of the curtailment estimator against known curtailments.

Paths are simulated with known curtailments, missed payments and catch-ups, pay-aheads, $1,000
rounding of disclosed balances through age 6, and either servicing convention. This tests the
*method*; whether real disclosures support it is decided privately with the rule in
docs/validation/CURTAILMENTS.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytest

from prepay import periods
from prepay.evaluation.curtailment import (
    LoanMonths,
    estimate,
    scheduled_principal,
    summary,
)
from prepay.finance.amortization import level_payment

START = periods.month(2015, 1)


@dataclass
class Simulated:
    months: LoanMonths
    truth: np.ndarray  # true curtailment per row (USD)


def simulate(
    loans: int,
    horizon: int,
    *,
    convention: str,
    seed: int,
    curtail_prob: float = 0.03,
    miss_prob: float = 0.02,
    ahead_prob: float = 0.01,
    start: int = START,
) -> Simulated:
    rng = np.random.default_rng(seed)
    upb0 = rng.uniform(1e5, 5e5, loans).round(2)
    rate = rng.choice([0.03, 0.04, 0.05, 0.06, 0.07], loans)
    term = np.full(loans, 360)
    payment0 = level_payment(upb0, rate, term.astype(float))
    balance = upb0.copy()
    remaining = term.copy()
    ddlpi = np.full(loans, start)  # first installment due start + 1
    behind = np.zeros(loans, dtype=bool)
    rows: dict[str, list[np.ndarray]] = {
        k: [] for k in ("bp", "b", "dp", "d", "rem", "age", "m", "c")
    }
    reported_prev = balance.copy()
    for age in range(1, horizon + 1):
        month = start + age
        miss = ~behind & (rng.random(loans) < miss_prob)
        ahead = ~behind & ~miss & (rng.random(loans) < ahead_prob)
        k = np.where(miss, 0, np.where(behind | ahead, 2, 1))
        behind = miss
        scheduled = scheduled_principal(balance, rate, k, remaining, payment0, convention)
        balance = balance - scheduled
        remaining = remaining - k
        curtail = (k >= 1) & (rng.random(loans) < curtail_prob)
        amount = np.where(curtail, np.minimum(rng.uniform(200, 8000, loans), 0.2 * balance), 0.0)
        balance = balance - amount
        ddlpi = ddlpi + k
        reported = np.where(age <= 6, np.round(balance, -3), np.round(balance, 2))
        for key, value in (
            ("bp", reported_prev),
            ("b", reported),
            ("dp", ddlpi - k),
            ("d", ddlpi),
            ("rem", remaining + k),
            ("age", np.full(loans, age - 1)),
            ("m", np.full(loans, month)),
            ("c", amount),
        ):
            rows[key].append(np.asarray(value))
        reported_prev = reported
    cat = {k: np.concatenate(v) for k, v in rows.items()}
    n = cat["b"].shape[0]
    months = LoanMonths(
        balance_prev=cat["bp"].astype(float),
        balance=cat["b"].astype(float),
        ddlpi_prev=cat["dp"].astype(np.int64),
        ddlpi=cat["d"].astype(np.int64),
        note_rate=np.tile(rate, horizon),
        original_upb=np.tile(upb0, horizon),
        original_term=np.tile(term, horizon),
        remaining_prev=cat["rem"].astype(np.int64),
        age_prev=cat["age"].astype(np.int64),
        month=cat["m"].astype(np.int64),
        terminal=np.zeros(n, dtype=bool),
        modified=np.zeros(n, dtype=bool),
        deferred=np.zeros(n, dtype=bool),
    )
    return Simulated(months, cat["c"])


def _scores(sim: Simulated, convention: str) -> tuple[float, float]:
    result = estimate(sim.months, convention=convention)  # type: ignore[arg-type]
    eligible = result.eligible
    truth = (sim.truth >= 500) & eligible
    found = (result.curtailment > 0) & eligible
    recall = float((found & truth).sum() / truth.sum())
    precision = float((found & (sim.truth > 0)).sum() / found.sum())
    return recall, precision


def test_matching_convention_meets_the_preregistered_synthetic_rule() -> None:
    """Recall >= 0.9 and precision >= 0.95 for curtailments >= $500 (CURTAILMENTS.md)."""
    for convention in ("no_recast", "recast"):
        sim = simulate(2000, 48, convention=convention, seed=1)
        recall, precision = _scores(sim, convention)
        assert recall >= 0.9, convention
        assert precision >= 0.95, convention
        result = estimate(sim.months, convention=convention)  # type: ignore[arg-type]
        found = result.curtailment[result.eligible & (sim.truth > 0)]
        np.testing.assert_allclose(found, sim.truth[result.eligible & (sim.truth > 0)], atol=0.02)


def test_the_wrong_convention_invents_curtailments() -> None:
    """Re-amortizing a no-recast loan's balance (the run-off residual's convention) reports the
    original payment's excess over the recast payment as curtailment every later month."""
    sim = simulate(2000, 48, convention="no_recast", seed=2)
    _, precision = _scores(sim, "recast")
    assert precision < 0.5
    # The opposite mismatch turns every month after a curtailment into a negative residual.
    sim = simulate(2000, 48, convention="recast", seed=3)
    result = estimate(sim.months, convention="no_recast")
    stats = summary(result, sim.months.balance_prev)
    assert stats["negative_residual_share"] > 0.05


def test_installment_counts_absorb_missed_and_catch_up_payments() -> None:
    sim = simulate(1500, 36, convention="no_recast", seed=4, curtail_prob=0.0, miss_prob=0.05)
    result = estimate(sim.months)
    assert set(np.unique(result.installments[result.eligible])) >= {0, 1, 2}
    assert np.all(result.curtailment == 0.0)  # no false curtailments without real ones
    ignoring = estimate(
        LoanMonths(
            **{
                **{f: getattr(sim.months, f) for f in sim.months.__slots__},
                "ddlpi": sim.months.ddlpi_prev + 1,  # pretend every month paid one installment
            }
        )
    )
    assert np.mean(ignoring.curtailment[ignoring.eligible] > 0) > 0.02  # catch-ups look curtailed


def test_rounded_and_transition_months_are_excluded_with_reasons() -> None:
    sim = simulate(200, 60, convention="no_recast", seed=5, start=periods.month(2018, 6))
    result = estimate(sim.months)
    rounded = sim.months.age_prev <= 6
    assert not result.eligible[rounded].any()
    assert set(result.exclusion[rounded]) == {"balance may be rounded to $1,000"}
    transition = (sim.months.month == periods.month(2019, 5)) & ~rounded
    assert set(result.exclusion[transition]) == {"reporting-cycle transition"}
    stats = summary(result, sim.months.balance_prev)
    assert stats["exclusions"]["balance may be rounded to $1,000"] == int(rounded.sum())
    assert stats["one_installment_within_dead_band_share"] > 0.9
    assert 0 < stats["implied_curtailment_smm"] < 0.01


def test_scheduled_principal_matches_the_level_payment_schedule() -> None:
    balance = np.array([200_000.0])
    rate = np.array([0.06])
    payment = level_payment(balance, rate, np.array([360.0]))
    one = scheduled_principal(balance, rate, np.array([1]), np.array([360]), payment, "no_recast")
    assert one[0] == pytest.approx(payment[0] - 1000.0)
    two = scheduled_principal(balance, rate, np.array([2]), np.array([360]), payment, "no_recast")
    second = payment[0] - (balance[0] - one[0]) * 0.005
    assert two[0] == pytest.approx(one[0] + second)
    zero = scheduled_principal(balance, rate, np.array([0]), np.array([360]), payment, "recast")
    assert zero[0] == 0.0
