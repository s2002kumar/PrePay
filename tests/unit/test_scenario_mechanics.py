"""Scenario mechanics against independent re-derivations from the spec (R2 oracle audit).

- Rate paths follow ARCHITECTURE §6: flat holds the last observed rate; parallel shifts it; custom
  holds its last value; the 15-year series keeps the t0 spread; history is never changed.
- Features along a hypothetical path equal naive per-row loops written from MODELING §4 and
  ADR 0003 §6-§7 (and the derived-feature definitions), not from the vectorized code.
- Coupons never move with a scenario (FINANCIAL_CONVENTIONS §3).
- Metamorphic: for a level-free model monotone in incentive, lower scenario rates return more
  principal early (FINANCIAL_CONVENTIONS §6.8). From month 2 on, because month 1 uses the rate
  known at the end of t0, which no scenario changes.
"""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from prepay import periods
from prepay.features.batch import PanelBatch
from prepay.features.derived import augment
from prepay.features.machine import LoanStatics, RatePath, compute_features
from prepay.finance import CreditAssumptions
from prepay.finance.amortization import level_payment
from prepay.scenarios.pools import demo_pools
from prepay.scenarios.projection import project_pool
from prepay.scenarios.rates import RateScenario, ScenarioError, scenario_path

START = periods.month(2000, 1)
T0 = periods.month(2026, 6)


def history() -> RatePath:
    rng = np.random.default_rng(7)
    months = T0 - START + 1
    walk = np.cumsum(rng.normal(0, 0.12, months))
    r30 = np.clip(walk - walk[-1] + 6.5, 2.5, 11.0)  # ends at 6.5%: every shock stays valid
    r15 = r30 - 0.6 + rng.normal(0, 0.03, months)
    return RatePath(START, r30, r15, np.zeros(months, dtype=bool))


def statics() -> LoanStatics:
    n = 3
    obj = np.array(["P", "P", "C"], dtype=object)
    return LoanStatics(
        note_rate_pct=np.array([6.5, 3.25, 4.875]),
        original_loan_term=np.array([360, 180, 360]),
        first_payment_month=np.array([periods.month(2007, 3), periods.month(2016, 9), T0 - 2]),
        maturity_month=np.array([periods.month(2037, 2), periods.month(2031, 8), T0 - 2 + 359]),
        original_upb=np.array([250_000.0, 180_000.0, 410_000.0]),
        credit_score=np.full(n, 740.0),
        original_ltv=np.full(n, 80.0),
        original_dti=np.full(n, 36.0),
        mi_pct=np.zeros(n),
        number_of_units=np.ones(n),
        number_of_borrowers=np.full(n, 2.0),
        loan_purpose=obj,
        occupancy_status=np.array(["P"] * n, dtype=object),
        channel=np.array(["R"] * n, dtype=object),
        first_time_homebuyer=np.array(["N"] * n, dtype=object),
        property_type=np.array(["SF"] * n, dtype=object),
        property_state=np.array(["CA", "TX", "NY"], dtype=object),
    )


def test_scenario_paths_follow_their_definitions() -> None:
    base = history()
    last30, last15 = base.rate_30y[-1], base.rate_15y[-1]
    for scenario, expected in (
        (RateScenario("flat"), np.full(24, last30)),
        (RateScenario("parallel", 150.0), np.full(24, last30 + 1.5)),
        (RateScenario("custom", path_30y=(5.0, 5.5)), np.r_[5.0, np.full(23, 5.5)]),
    ):
        path = scenario_path(base, T0, 24, scenario)
        np.testing.assert_array_equal(path.rate_30y[: base.rate_30y.size], base.rate_30y)
        np.testing.assert_allclose(path.rate_30y[base.rate_30y.size :], expected)
        np.testing.assert_allclose(
            path.rate_15y[base.rate_15y.size :], expected - (last30 - last15)
        )
        assert path.hypothetical_from == T0 + 1
    with pytest.raises(ScenarioError):
        scenario_path(base, T0, 24, RateScenario("parallel", -900.0))


def _naive_row(loans: LoanStatics, i: int, t: int, path: RatePath) -> dict[str, float]:
    """MODELING §4 / ADR 0003 §6-§7 one row at a time, with plain loops."""

    def rate(m: int) -> float:
        series = path.rate_15y if loans.original_loan_term[i] <= 180 else path.rate_30y
        return float(series[m - path.first_month])

    note, fp = float(loans.note_rate_pct[i]), int(loans.first_payment_month[i])
    market = rate(t - 1)
    burnout = sum(1 for j in range(fp, t) if (note - rate(j - 1)) * 100 > 50)
    seen = [rate(m) for m in range(fp - 1, t - 1)]
    remaining = int(loans.maturity_month[i]) - t + 1
    a_market = float(level_payment(1.0, market / 100, remaining))
    a_note = float(level_payment(1.0, note / 100, remaining))
    return {
        "market_rate_t1": market,
        "incentive_bps": (note - market) * 100,
        "rate_change_6m_bps": (market - rate(t - 7)) * 100,
        "burnout_months": float(burnout),
        "sato_bps": (note - rate(fp - 1)) * 100,
        "loan_age": float(t - fp + 1),
        "remaining_payments": float(remaining),
        "note_rate_pct": note,
        "new_opportunity_bps": (min(seen) - market) * 100 if seen else 0.0,
        "payment_saving_pct": 100 * (1 - a_market / a_note),
    }


@pytest.mark.parametrize("shock", [-200.0, 0.0, 175.0])
def test_features_along_a_scenario_match_naive_loops(shock: float) -> None:
    loans, base = statics(), history()
    path = scenario_path(base, T0, 36, RateScenario("parallel", shock))
    index = np.repeat(np.arange(loans.count), 36)
    target = np.tile(np.arange(T0 + 1, T0 + 37), loans.count)
    batch = augment(
        PanelBatch(
            loan_id=index.astype(object),
            target_month=target,
            outcome_class=np.zeros(target.size, dtype=np.int64),
            exposure_upb=np.zeros(target.size),
            features=compute_features(loans, path, index, target),
        ),
        path,
    )
    for row in range(target.size):
        expected = _naive_row(loans, int(index[row]), int(target[row]), path)
        for name, value in expected.items():
            assert float(batch.features[name][row]) == pytest.approx(value, abs=1e-9), (
                name,
                row,
            )


def test_coupons_and_origination_spreads_never_move_with_a_scenario() -> None:
    loans, base = statics(), history()
    index = np.repeat(np.arange(loans.count), 12)
    target = np.tile(np.arange(T0 + 1, T0 + 13), loans.count)
    outputs = [
        compute_features(
            loans, scenario_path(base, T0, 12, RateScenario("parallel", s)), index, target
        )
        for s in (-200.0, 0.0, 200.0)
    ]
    for name in ("note_rate_pct", "sato_bps", "loan_age", "remaining_payments"):
        for other in outputs[1:]:
            np.testing.assert_array_equal(outputs[0][name], other[name])


class LevelFreeMonotone:
    """p_prepay = logistic(-5 + 0.01 * incentive): monotone in incentive, blind to rate level."""

    name = "level_free_monotone"

    def predict_proba(self, batch: PanelBatch) -> np.ndarray:
        incentive = np.asarray(batch.features["incentive_bps"], dtype=np.float64)
        prepay = 1.0 / (1.0 + np.exp(-(-5.0 + 0.01 * incentive)))
        return np.column_stack([1.0 - prepay, prepay, np.zeros_like(prepay)])


def test_lower_rates_return_more_principal_early_for_a_monotone_model() -> None:
    pool = next(iter(demo_pools().values()))
    base = history()
    credit = CreditAssumptions(severity=0.0, recovery_lag_months=0)
    results = {
        s: project_pool(pool, LevelFreeMonotone(), base, RateScenario("parallel", s), credit)
        for s in (-200.0, -100.0, 0.0, 100.0, 200.0)
    }
    # Month 1 uses the rate known at the end of t0 (history): no scenario can move it.
    first_month = {results[s].ledger.voluntary_prepay_principal[0] for s in results}
    assert len(first_month) == 1
    # From month 2 on, lower rates mean larger incentives and more payoff principal.
    second_month = [results[s].ledger.voluntary_prepay_principal[1] for s in sorted(results)]
    assert all(a > b for a, b in itertools.pairwise(second_month))
    returned = [results[s].summary(24)["principal_returned_fraction_24m"] for s in sorted(results)]
    assert all(a > b for a, b in itertools.pairwise(returned))
    # The contractual coupon is untouched: interest accrued in month 1 is identical.
    first_interest = {results[s].ledger.contractual_interest_accrued[0] for s in results}
    assert len(first_interest) == 1
