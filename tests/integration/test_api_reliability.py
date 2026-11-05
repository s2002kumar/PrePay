"""Reliability safeguards in the demo API: verdict, model range and credit as an assumption."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prepay.api.app import create_app
from prepay.api.schemas import CreditIn
from prepay.reliability import support
from prepay.scenarios.rates import RateScenario

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


def test_model_range_names_each_family_once_and_keeps_the_spread(client: TestClient) -> None:
    # Regression: the selected model was listed again under its family name (B2, B1, B2, M1).
    for horizon in (12, 120, 360):
        body = project(
            client, compare_to={"kind": "parallel", "shock_bps": 200}, horizon_months=horizon
        )
        for side in ("a", "b"):
            spread = body[side]["model_range"]
            assert len(spread["models"]) == len(set(spread["models"]))
            assert set(spread["models"]) == {"B1_lookup", "B2_logistic", "M1_lightgbm"}
            assert spread["models"][0] == body["model"]  # the served model leads, as before
    # The spread itself is the min and max over the family projections, unchanged by naming.
    service = client.app.state.service
    scenario, credit = RateScenario("parallel", 200, ()), CreditIn()
    served = service.model_range(POOL, scenario, credit, 60)
    for metric in ("cash_wal_years", "principal_returned_fraction_24m", "ending_upb_horizon_usd"):
        values = [
            service.result(POOL, scenario, credit, key).summary(60)[metric]
            for key in service.models
        ]
        assert getattr(served, metric).min == min(values)
        assert getattr(served, metric).max == max(values)


def test_served_verdict_rule_states_the_implemented_thresholds(client: TestClient) -> None:
    rule = client.get("/api/methodology").json()["metrics"]["reliability_verdict"]["formula"]
    assert f">= {support.OUTSIDE_UNSUPPORTED:.0%}" in rule
    assert f"outside share >= {support.OUTSIDE_EXTRAPOLATING:.0%}" in rule
    both = support.OUTSIDE_OR_SPARSE_EXTRAPOLATING
    assert f"outside plus thinly supported share >= {both:.0%}" in rule
    assert f"fewer than {support.MIN_CELL_ROWS:,} training rows" in rule
    assert f"fewer than {support.MIN_CELL_PAYOFFS} training payoffs" in rule
    assert "PSI" in rule  # pools are judged on row support only (ADR 0009 amendment 1)
    assert ">= 20% outside or in joint" not in rule  # the superseded wording
    # The stated rule and decide() agree at and around every threshold.
    cases = [
        (0.25, 0.0),
        (0.2499, 0.0),
        (0.05, 0.0),
        (0.0499, 0.0),
        (0.0, 0.20),
        (0.10, 0.10),
        (0.0, 0.1999),
        (0.04, 0.15),
        (0.0, 0.0),
    ]
    for outside, sparse in cases:
        expected = (
            "unsupported"
            if outside >= 0.25
            else "extrapolating"
            if outside >= 0.05 or outside + sparse >= 0.20
            else "supported"
        )
        assert support.decide(outside, sparse) == expected


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
