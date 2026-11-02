"""What the product serves is the audited engine's ledger, and every summary follows from it.

The engine is audited against exact oracles (tests/financial, docs/validation/ORACLE_AUDIT.md).
These tests close the loop for the product surface:

1. the API's monthly rows equal the engine's ledger for the same pool, model, scenario and
   assumptions, exactly;
2. every summary number and every derived monthly column is recomputed here from the served
   rows with plain arithmetic, independently of :mod:`prepay.finance.metrics`.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from prepay.api.app import create_app
from prepay.api.bundle import load_bundle
from prepay.api.schemas import CreditIn, ScenarioIn
from prepay.api.service import ProjectionService, to_scenario

POOLS = (
    "fictional-2021-low-coupon",
    "fictional-2023-high-coupon",
    "fictional-2013-seasoned",
    "fictional-2020-15-year",
)
SCENARIOS: tuple[dict[str, Any], ...] = (
    {"kind": "flat"},
    {"kind": "parallel", "shock_bps": -200},
    {"kind": "custom", "path_30y_pct": [4.0 + 0.1 * k for k in range(24)]},
)
ROW_FIELDS = {
    "beginning_upb_usd": "beginning_upb",
    "scheduled_principal_usd": "scheduled_principal",
    "voluntary_prepay_principal_usd": "voluntary_prepay_principal",
    "credit_exit_principal_usd": "credit_exit_principal",
    "recoveries_received_usd": "recoveries_received",
    "illustrative_credit_loss_usd": "illustrative_credit_loss",
    "contractual_interest_accrued_usd": "contractual_interest_accrued",
    "ending_upb_usd": "ending_upb",
}
REL = 1e-12  # summation order differs (pairwise in NumPy, sequential here)


@pytest.fixture(scope="module")
def client(demo_bundle: Path) -> TestClient:
    return TestClient(create_app(demo_bundle, None, warm=False, rate_limit_per_minute=10**6))


def served(client: TestClient, pool: str, scenario: dict[str, Any], horizon: int) -> dict[str, Any]:
    body = {"pool_id": pool, "scenario": scenario, "horizon_months": horizon}
    response = client.post("/api/project", json=body)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def column(rows: list[dict[str, Any]], name: str) -> list[float]:
    return [float(r[name]) for r in rows]


def test_served_rows_are_the_engine_ledger_exactly(client: TestClient, demo_bundle: Path) -> None:
    service = ProjectionService(load_bundle(demo_bundle))
    for pool in POOLS:
        for scenario in SCENARIOS:
            rows = served(client, pool, scenario, 360)["a"]["monthly"]
            ledger = service.result(pool, to_scenario(ScenarioIn(**scenario)), CreditIn()).ledger
            assert len(rows) == min(360, ledger.months)
            for name, attribute in ROW_FIELDS.items():
                engine = getattr(ledger, attribute)[: len(rows)].tolist()
                assert column(rows, name) == engine, (pool, scenario["kind"], name)


def check_window(scenario_out: dict[str, Any], horizon: int) -> bool:
    """Recompute one served scenario's summary from its rows; True if full-life WAL was checked."""
    rows, summary = scenario_out["monthly"], scenario_out["summary"]
    initial = rows[0]["beginning_upb_usd"]
    sched = column(rows, "scheduled_principal_usd")
    prepay = column(rows, "voluntary_prepay_principal_usd")
    exits = column(rows, "credit_exit_principal_usd")
    recoveries = column(rows, "recoveries_received_usd")
    begin, end = column(rows, "beginning_upb_usd"), column(rows, "ending_upb_usd")
    interest = column(rows, "contractual_interest_accrued_usd")
    cash = [s + p + r for s, p, r in zip(sched, prepay, recoveries, strict=True)]

    # Money is conserved month by month and over the window; balances chain.
    for k in range(len(rows)):
        assert begin[k] - sched[k] - prepay[k] - exits[k] == pytest.approx(end[k], abs=1e-6)
        if k + 1 < len(rows):
            assert end[k] == begin[k + 1]
    total_out = math.fsum(sched) + math.fsum(prepay) + math.fsum(exits)
    assert initial == pytest.approx(total_out + end[-1], rel=REL)

    # Horizon totals are sums of the rows they summarize.
    totals = {
        "scheduled_principal_horizon_usd": sched,
        "voluntary_prepay_principal_horizon_usd": prepay,
        "recoveries_received_horizon_usd": recoveries,
        "illustrative_credit_loss_horizon_usd": column(rows, "illustrative_credit_loss_usd"),
        "contractual_interest_accrued_horizon_usd": interest,
    }
    for key, values in totals.items():
        assert summary[key] == pytest.approx(math.fsum(values), rel=REL, abs=1e-9), key
    assert summary["ending_upb_horizon_usd"] == end[-1]
    assert summary["horizon_months"] == len(rows)

    # Cumulative principal returned, and the 12/24-month and horizon fractions.
    running = 0.0
    for k, row in enumerate(rows):
        running += cash[k]
        expected = running / initial
        assert row["cumulative_principal_returned_fraction"] == pytest.approx(expected, rel=REL)
    returned = math.fsum(cash) / initial
    assert summary["principal_returned_fraction_horizon"] == pytest.approx(returned, rel=REL)
    for months in (12, 24):
        if len(rows) >= months:
            early = math.fsum(cash[:months]) / initial
            key = f"principal_returned_fraction_{months}m"
            assert summary[key] == pytest.approx(early, rel=REL)

    # Model CPR: 1 - (1 - SMM)^12 with SMM = payoffs / balance after scheduled principal.
    for k, row in enumerate(rows):
        surviving = begin[k] - sched[k]
        if surviving > 0:
            cpr = 1 - (1 - prepay[k] / surviving) ** 12
            assert row["cpr_model"] == pytest.approx(cpr, rel=1e-9, abs=1e-15)

    # Full-life cash WAL, when the served window covers the whole life of the pool.
    resolved = end[-1] <= 1e-6 and summary["pending_recoveries_horizon_usd"] <= 1e-6
    if horizon < 360 or not resolved or summary["cash_wal_years"] is None:
        return False
    weighted = math.fsum((k + 1) / 12 * c for k, c in enumerate(cash))
    assert summary["cash_wal_years"] == pytest.approx(weighted / math.fsum(cash), rel=REL)
    return True


@pytest.mark.parametrize("horizon", [12, 60, 360])
def test_every_summary_number_follows_from_the_served_rows(
    client: TestClient, horizon: int
) -> None:
    full_life = [
        check_window(served(client, pool, scenario, horizon)["a"], horizon)
        for pool in POOLS
        for scenario in SCENARIOS
    ]
    if horizon == 360:
        assert any(full_life)  # at least one pool's full life fits in 360 served months
