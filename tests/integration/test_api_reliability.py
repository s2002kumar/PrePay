"""Reliability safeguards in the demo API: verdict, model range and credit as an assumption."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prepay.api.app import create_app

POOL = "fictional-2023-high-coupon"


@pytest.fixture(scope="module")
def client(demo_bundle: Path) -> TestClient:
    return TestClient(create_app(demo_bundle, None, warm=False, rate_limit_per_minute=1000))


def project(client: TestClient, **overrides: object) -> dict:
    body = {"pool_id": POOL, "scenario": {"kind": "flat"}, "horizon_months": 36}
    body.update(overrides)
    response = client.post("/api/project", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_every_scenario_states_its_applicability_verdict(client: TestClient) -> None:
    body = project(client, compare_to={"kind": "parallel", "shock_bps": -200})
    for side in ("a", "b"):
        reliability = body[side]["reliability"]
        assert reliability["verdict"] in ("supported", "extrapolating", "unsupported")
        assert 0.0 <= reliability["outside_share"] <= 1.0
        assert 0.0 <= reliability["outside_share"] + reliability["sparse_share"] <= 1.0 + 1e-12
        assert reliability["headline"] == (
            "range" if reliability["verdict"] == "unsupported" else "point"
        )


def test_rates_far_outside_training_are_flagged_and_warned(client: TestClient) -> None:
    path = [1.6] * 36  # far below every synthetic training rate
    body = project(client, scenario={"kind": "custom", "path_30y_pct": path})
    reliability = body["a"]["reliability"]
    assert reliability["verdict"] in ("extrapolating", "unsupported")
    assert reliability["outside_share_by_feature"]["market_rate_t1"] > 0.5
    assert any(reliability["verdict"] in w for w in body["warnings"])


def test_model_range_brackets_the_selected_model(client: TestClient) -> None:
    body = project(client, horizon_months=60)
    spread, summary = body["a"]["model_range"], body["a"]["summary"]
    assert body["model"] in spread["models"]
    assert len(spread["models"]) >= 3
    assert "not a confidence interval" in spread["note"]
    for metric in ("principal_returned_fraction_24m", "cash_wal_years", "ending_upb_horizon_usd"):
        low, high = spread[metric]["min"], spread[metric]["max"]
        assert low <= summary[metric] + 1e-12
        assert summary[metric] <= high + 1e-12


def test_credit_exits_are_a_labeled_assumption_unless_validated(client: TestClient) -> None:
    default = project(client)
    assert default["assumptions"]["credit_exits"].startswith("assumption")  # tiny world: few events
    none = project(client, credit={"annual_cdr_pct": 0.0})
    assert all(r["credit_exit_principal_usd"] == 0.0 for r in none["a"]["monthly"])
    assert "user-set" in none["assumptions"]["credit_exits"]
    heavy = project(client, credit={"annual_cdr_pct": 5.0})
    exits = sum(r["credit_exit_principal_usd"] for r in heavy["a"]["monthly"])
    default_exits = sum(r["credit_exit_principal_usd"] for r in default["a"]["monthly"])
    assert exits > default_exits
    for row in heavy["a"]["monthly"]:  # money is still conserved under the assumption
        out = (
            row["scheduled_principal_usd"]
            + row["voluntary_prepay_principal_usd"]
            + row["credit_exit_principal_usd"]
        )
        assert row["beginning_upb_usd"] - out == pytest.approx(row["ending_upb_usd"], abs=1e-6)


def test_credit_assumption_bounds_are_enforced(client: TestClient) -> None:
    for value in (-1.0, 25.0):
        response = client.post(
            "/api/project",
            json={
                "pool_id": POOL,
                "scenario": {"kind": "flat"},
                "credit": {"annual_cdr_pct": value},
            },
        )
        assert response.status_code == 422


def test_scenario_timing_is_disclosed_and_month_one_is_scenario_free(client: TestClient) -> None:
    body = project(client, compare_to={"kind": "parallel", "shock_bps": -200})
    assert "month 2" in body["assumptions"]["scenario_timing"]
    a, b = body["a"]["monthly"], body["b"]["monthly"]
    assert a[0]["voluntary_prepay_principal_usd"] == b[0]["voluntary_prepay_principal_usd"]
    assert a[1]["voluntary_prepay_principal_usd"] != b[1]["voluntary_prepay_principal_usd"]
    method = client.get("/api/methodology").json()
    assert any("month 2" in item for item in method["limitations"])
