"""Public demo API: contracts, validation, limits, security headers and serving guards."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prepay.api.app import MAX_BODY_BYTES, create_app
from prepay.api.bundle import BundleError, load_bundle
from prepay.modeling.lockbox import SealError

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


def test_health_declares_synthetic_artifacts(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["artifact_class"] == "synthetic"
    assert body["data_class"] == "fictional"


def test_pools_are_fictional_with_summaries(client: TestClient) -> None:
    body = client.get("/api/pools").json()
    assert body["data_class"] == "fictional"
    assert "Not Freddie Mac data" in body["notice"]
    assert len(body["pools"]) == 4
    for pool in body["pools"]:
        assert pool["fictional"] is True
        assert pool["current_upb_usd"] > 0
        assert "(fictional)" in pool["name"]
    one = client.get(f"/api/pools/{POOL}").json()["pool"]
    assert one["pool_id"] == POOL


def test_projection_contract_and_conservation(client: TestClient) -> None:
    body = project(client, compare_to={"kind": "parallel", "shock_bps": -200})
    assert body["data_class"] == "fictional"
    assert body["as_of"] == "2026-06"
    assert len(body["a"]["monthly"]) == 36
    assert body["b"]["label"] == "Parallel -200 bp"
    for row in body["a"]["monthly"]:
        exits = (
            row["scheduled_principal_usd"]
            + row["voluntary_prepay_principal_usd"]
            + row["credit_exit_principal_usd"]
        )
        assert row["beginning_upb_usd"] - exits == pytest.approx(row["ending_upb_usd"], abs=1e-6)
    a, b = body["a"]["summary"], body["b"]["summary"]
    assert body["a_minus_b"]["principal_returned_24m_pp"] == pytest.approx(
        (a["principal_returned_fraction_24m"] - b["principal_returned_fraction_24m"]) * 100
    )
    assert body["assumptions"]["coupon"].startswith("contract note rates are fixed")


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"horizon_months": 0}, "invalid_request"),
        ({"horizon_months": 361}, "invalid_request"),
        ({"unexpected": 1}, "invalid_request"),
        ({"pool_id": "../../etc"}, "invalid_request"),
        ({"scenario": {"kind": "custom"}}, "invalid_request"),
        ({"scenario": {"kind": "parallel", "shock_bps": 600}}, "invalid_request"),
        ({"scenario": {"kind": "custom", "path_30y_pct": [25.0]}}, "invalid_request"),
        ({"scenario": {"kind": "flat", "path_30y_pct": [5.0]}}, "invalid_request"),
        ({"credit": {"severity": 1.5}}, "invalid_request"),
        ({"scenario": {"kind": "custom", "path_30y_pct": [0.6]}}, "invalid_scenario"),
    ],
)
def test_invalid_requests_get_typed_422(client: TestClient, change: dict, code: str) -> None:
    body = {"pool_id": POOL, "scenario": {"kind": "flat"}, "horizon_months": 12, **change}
    response = client.post("/api/project", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code


def test_unknown_pool_is_404(client: TestClient) -> None:
    response = client.post("/api/project", json={"pool_id": "nope", "scenario": {"kind": "flat"}})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "unknown_pool"
    assert client.get("/api/pools/nope").status_code == 404


def test_oversized_body_is_413(client: TestClient) -> None:
    payload = json.dumps(
        {"pool_id": POOL, "scenario": {"kind": "flat"}, "padding": "x" * (MAX_BODY_BYTES + 10)}
    )
    response = client.post(
        "/api/project", content=payload, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_rate_limit_returns_429(demo_bundle: Path) -> None:
    limited = TestClient(create_app(demo_bundle, None, warm=False, rate_limit_per_minute=2))
    body = {"pool_id": POOL, "scenario": {"kind": "flat"}, "horizon_months": 6}
    codes = [limited.post("/api/project", json=body).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_security_headers_on_every_response(client: TestClient) -> None:
    for response in (client.get("/api/health"), client.get("/api/pools/nope")):
        assert "default-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"


def test_methodology_and_model_quality_are_labelled(client: TestClient) -> None:
    method = client.get("/api/methodology").json()
    for metric in method["metrics"].values():
        assert metric["unit"]
        assert metric["formula"]
    assert method["model"]["trained_on"].startswith("synthetic")
    quality = client.get("/api/model-quality").json()
    assert quality["synthetic"] is True
    assert quality["real_data_status"].startswith("BLOCKED")
    assert set(quality["holdout"]) <= {"test_a", "test_b", "test_c"}


def test_openapi_documents_the_projection_contract(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    assert "ProjectionRequest" in schema["components"]["schemas"]
    assert "/api/project" in schema["paths"]


def test_latency_is_sampled(client: TestClient) -> None:
    project(client)
    latency = client.get("/api/health").json()["project_latency_ms"]
    assert latency["count"] >= 1
    assert latency["p95"] >= latency["p50"] > 0


def test_bundle_guards(demo_bundle: Path, tmp_path: Path) -> None:
    tampered = tmp_path / "tampered"
    shutil.copytree(demo_bundle, tampered)
    model = tampered / "run" / "models" / "B0_psa.json"
    model.chmod(0o644)
    model.write_text(model.read_text().replace("1.0", "2.0"))
    with pytest.raises(SealError):
        load_bundle(tampered)
    unmarked = tmp_path / "unmarked"
    shutil.copytree(demo_bundle, unmarked)
    manifest = unmarked / "bundle-manifest.json"
    manifest.write_text(manifest.read_text().replace('"synthetic": true', '"synthetic": false'))
    with pytest.raises(BundleError, match="synthetic"):
        load_bundle(unmarked)
    with pytest.raises(BundleError, match="no demo bundle"):
        load_bundle(tmp_path / "missing")


def test_spa_is_served_without_path_traversal(demo_bundle: Path, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Prepay</title>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("do not serve")
    spa = TestClient(create_app(demo_bundle, dist, warm=False))
    assert "Prepay" in spa.get("/").text
    assert "Prepay" in spa.get("/scenario-lab").text
    assert spa.get("/assets/app.js").text == "console.log(1)"
    assert "do not serve" not in spa.get("/..%2fsecret.txt").text
    assert "do not serve" not in spa.get("/../secret.txt").text
    missing = spa.get("/api/nothing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
