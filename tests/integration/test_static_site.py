"""The static site holds exactly the API's responses on its grid (DEPLOYMENT §Static site)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prepay.api.app import create_app
from prepay.api.static import (
    HORIZONS,
    STATIC_SCENARIOS,
    assemble,
    build_site,
    export_static,
    scenario_body,
)

SMALL_GRID = ("flat", "p-100", "p200")
SMALL_HORIZONS = (12, 360)


@pytest.fixture(scope="module")
def static_data(demo_bundle: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("static") / "data"
    export_static(demo_bundle, out, scenarios=SMALL_GRID, horizons=SMALL_HORIZONS)
    return out


def _load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def test_grid_matches_the_web_ui_and_api_limits() -> None:
    assert STATIC_SCENARIOS[0] == "flat"
    assert len(STATIC_SCENARIOS) == 13  # web/src/static.ts and e2e/static.spec.ts expect 13
    assert {"p-200", "p-100", "p100", "p200"} <= set(STATIC_SCENARIOS)  # the live UI's presets
    assert HORIZONS == (12, 24, 60, 120, 240, 360)  # ScenarioLab HORIZONS
    assert scenario_body("p-300") == {"kind": "parallel", "shock_bps": -300}
    with pytest.raises(ValueError, match="not a static scenario"):
        scenario_body("ramp:5.00:12")


def test_reassembled_responses_equal_the_api(static_data: Path, demo_bundle: Path) -> None:
    index = _load(static_data / "index.json")
    assert isinstance(index, dict)
    client = TestClient(create_app(demo_bundle, None, warm=False, rate_limit_per_minute=10**6))
    pool_id = next(iter(index["pools"]))
    projections = {
        code: _load(static_data / "projections" / pool_id / f"{code}.json") for code in SMALL_GRID
    }
    for horizon in SMALL_HORIZONS:
        pairs = _load(static_data / "pairs" / pool_id / f"{horizon}.json")
        body = {
            "pool_id": pool_id,
            "scenario": scenario_body("p-100"),
            "compare_to": scenario_body("p200"),
            "horizon_months": horizon,
        }
        served = client.post("/api/project", json=body).json()
        rebuilt = assemble(index, projections, pairs, pool_id, "p-100", "p200", horizon)  # type: ignore[arg-type]
        assert rebuilt == served
        assert len(rebuilt["a"]["monthly"]) == min(horizon, len(projections["p-100"]["monthly"]))  # type: ignore[index]


def test_get_payloads_are_the_api_payloads(static_data: Path, demo_bundle: Path) -> None:
    client = TestClient(create_app(demo_bundle, None, warm=False))
    for name in ("pools", "scenarios", "methodology", "model-quality"):
        assert _load(static_data / "api" / f"{name}.json") == client.get(f"/api/{name}").json()
    health = _load(static_data / "api" / "health.json")
    assert isinstance(health, dict)
    assert health["artifact_class"] == "synthetic"
    assert health["data_class"] == "fictional"


def test_site_has_an_entry_per_route(demo_bundle: Path, tmp_path: Path) -> None:
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<!doctype html><title>Prepay</title>", encoding="utf-8")
    site = tmp_path / "site"
    # A one-scenario grid keeps this fast; `make static-site` builds the full grid.
    build_site(demo_bundle, web, site, scenarios=("flat",), horizons=(12,))
    for route in ("portfolio", "scenario-lab", "model-quality", "methodology"):
        assert (site / route / "index.html").read_text(encoding="utf-8").startswith("<!doctype")
    assert (site / "404.html").is_file()
    assert (site / "data" / "index.json").is_file()
    with pytest.raises(FileNotFoundError, match="no static web build"):
        build_site(demo_bundle, tmp_path / "missing", tmp_path / "other")


def test_latency_tool_reports_cold_and_cached_requests(demo_bundle: Path) -> None:
    from prepay.api.latency import measure_latency

    report = measure_latency(demo_bundle, cold=2, warm=3)
    assert report["cold_two_scenario_request"]["count"] == 2
    assert report["cached_two_scenario_request"]["count"] == 3
    assert report["cached_two_scenario_request"]["p50_ms"] > 0
    assert report["peak_rss_mib"] > 0
