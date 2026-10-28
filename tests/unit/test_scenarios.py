"""Rate scenarios, fictional pools and model-driven projection (incl. FINANCIAL §6.7)."""

from __future__ import annotations

import numpy as np
import pytest

from prepay import periods
from prepay.features.machine import RatePath
from prepay.features.panel import PanelBatch
from prepay.finance import CreditAssumptions, conservation_residuals
from prepay.scenarios.pools import DEMO_AS_OF, DEMO_POOL_SPECS, demo_pool, demo_pools
from prepay.scenarios.projection import compare, project_pool
from prepay.scenarios.rates import RateScenario, ScenarioError, scenario_path

T0 = DEMO_AS_OF
CREDIT = CreditAssumptions(severity=0.35, recovery_lag_months=6)


def history() -> RatePath:
    first = periods.month(1999, 1)
    months = T0 - first + 1
    r30 = 7.0 - 3.0 * np.sin(np.linspace(0, 3, months)) + 0.5
    return RatePath(first, r30, r30 - 0.6, np.arange(first, T0 + 1) >= periods.month(2022, 11))


class ConstantHazard:
    def predict_proba(self, batch: PanelBatch) -> np.ndarray:
        n = batch.target_month.shape[0]
        return np.tile([0.988, 0.01, 0.002], (n, 1))


class IncentiveHazard:
    """Payoff rises smoothly with refinance incentive (a monotone stand-in model)."""

    def predict_proba(self, batch: PanelBatch) -> np.ndarray:
        incentive = np.asarray(batch.features["incentive_bps"], dtype=float)
        prepay = 0.002 + 0.04 / (1 + np.exp(-(incentive - 75) / 25))
        credit = np.full_like(prepay, 0.0005)
        return np.column_stack([1 - prepay - credit, prepay, credit])


def test_flat_parallel_and_custom_paths() -> None:
    h = history()
    flat = scenario_path(h, T0, 12, RateScenario("flat"))
    up = scenario_path(h, T0, 12, RateScenario("parallel", 100.0))
    custom = scenario_path(h, T0, 12, RateScenario("custom", path_30y=(5.0, 4.5)))
    last = h.rate_30y[-1]
    np.testing.assert_allclose(flat.rate_30y[-12:], last)
    np.testing.assert_allclose(up.rate_30y[-12:], last + 1.0)
    np.testing.assert_allclose(custom.rate_30y[-12:], [5.0, *[4.5] * 11])
    spread = h.rate_30y[-1] - h.rate_15y[-1]
    np.testing.assert_allclose(up.rate_30y[-12:] - up.rate_15y[-12:], spread)
    assert up.hypothetical_from == T0 + 1
    np.testing.assert_array_equal(up.rate_30y[: h.rate_30y.size], h.rate_30y)


@pytest.mark.parametrize(
    "scenario",
    [
        RateScenario("parallel", 600.0),
        RateScenario("custom", path_30y=()),
        RateScenario("custom", path_30y=(25.0,)),
        RateScenario("parallel", -700.0),
        RateScenario("custom", path_30y=(0.6,)),
    ],
)
def test_implausible_scenarios_are_rejected(scenario: RateScenario) -> None:
    with pytest.raises(ScenarioError):
        scenario_path(history(), T0, 12, scenario)


def test_6_7_rate_shock_with_fixed_hazards_leaves_contractual_flows_identical() -> None:
    pool = demo_pool(DEMO_POOL_SPECS[1])
    base = project_pool(pool, ConstantHazard(), history(), RateScenario("flat"), CREDIT)
    shocked = project_pool(
        pool, ConstantHazard(), history(), RateScenario("parallel", 200.0), CREDIT
    )
    for field in (
        "scheduled_principal",
        "contractual_interest_accrued",
        "voluntary_prepay_principal",
        "credit_exit_principal",
        "ending_upb",
        "recoveries_received",
    ):
        np.testing.assert_array_equal(getattr(base.ledger, field), getattr(shocked.ledger, field))
    assert not np.array_equal(base.rate_path_30y, shocked.rate_path_30y)


def test_lower_rates_return_principal_sooner_under_a_monotone_model() -> None:
    pool = demo_pool(DEMO_POOL_SPECS[1])
    results = {
        shock: project_pool(
            pool, IncentiveHazard(), history(), RateScenario("parallel", shock), CREDIT
        )
        for shock in (-200.0, 0.0, 200.0)
    }
    for r in results.values():
        assert conservation_residuals(r.ledger).ok
        assert r.ledger.ending_upb[-1] == 0.0
    returned = {k: v.summary(24)["principal_returned_fraction_24m"] for k, v in results.items()}
    assert returned[-200.0] > returned[0.0] > returned[200.0]
    delta = compare(results[0.0], results[-200.0], 24)
    assert delta["cash_wal_months"] < 0
    assert delta["principal_returned_24m_pp"] > 0
    first = results[-200.0].monthly(24)[0]
    assert first["month"] == periods.to_iso(T0 + 1)
    # Month t0+1 uses only rates through t0, so it is identical across scenarios.
    assert first["voluntary_prepay_principal_usd"] == pytest.approx(
        results[200.0].monthly(24)[0]["voluntary_prepay_principal_usd"]
    )


def test_out_of_support_share_is_reported() -> None:
    pool = demo_pool(DEMO_POOL_SPECS[0])
    narrow = {"incentive_bps": {"low": -50.0, "high": 50.0}}
    result = project_pool(
        pool, IncentiveHazard(), history(), RateScenario("flat"), CREDIT, support=narrow
    )
    assert result.summary(24)["max_out_of_support_share_horizon"] > 0.9
    wide = {"incentive_bps": {"low": -1e4, "high": 1e4}}
    result = project_pool(
        pool, IncentiveHazard(), history(), RateScenario("flat"), CREDIT, support=wide
    )
    assert result.summary(24)["max_out_of_support_share_horizon"] == 0.0


def test_demo_pools_are_deterministic_fictional_and_active() -> None:
    a, b = demo_pools(), demo_pools()
    assert set(a) == {spec.pool_id for spec in DEMO_POOL_SPECS}
    for pool_id, pool in a.items():
        np.testing.assert_array_equal(pool.current_upb, b[pool_id].current_upb)
        assert pool.fictional
        assert np.all(pool.current_upb > 0)
        assert np.all(pool.current_upb < pool.statics.original_upb)
        assert np.all(pool.remaining_payments >= 1)
        summary = pool.summary()
        assert summary["fictional"] is True
        assert abs(sum(summary["term_mix"].values()) - 1.0) < 1e-9
    low = a["fictional-2021-low-coupon"].summary()["wac_pct"]
    high = a["fictional-2023-high-coupon"].summary()["wac_pct"]
    assert low < 3.5 < 6.5 < high
