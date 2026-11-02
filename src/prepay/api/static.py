"""Static export of the fictional demo for hosts that serve files only (DEPLOYMENT §Static site).

Every number is taken from the running API (a FastAPI test client on the demo bundle) for a fixed
grid of pools, scenarios and horizons, at the default credit assumptions. The export only
restructures those responses so that each scenario's monthly ledger is stored once:

- ``api/<name>.json``: the GET payloads (pools, scenarios, methodology, model quality, health);
- ``projections/<pool>/<code>.json``: one scenario's full-horizon monthly rows, plus its summary,
  reliability and model range at each horizon;
- ``pairs/<pool>/<horizon>.json``: per scenario pair, the A-B deltas and the warnings;
- ``index.json``: the grid and the per-pool response fields.

:func:`assemble` rebuilds a projection response from these files, and the export reassembles
every response it covers and requires exact equality with the API's. The web UI's static
adapter (``web/src/static.ts``) mirrors :func:`assemble`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from prepay.api.app import create_app

STATIC_FORMAT = 1
#: Precomputed scenario codes (the UI's URL codes): flat plus parallel shifts in 50 bp steps.
STATIC_SCENARIOS: tuple[str, ...] = (
    "flat",
    *(f"p{bps}" for bps in (-300, -250, -200, -150, -100, -50, 50, 100, 150, 200, 250, 300)),
)
NO_COMPARISON = "none"
HORIZONS: tuple[int, ...] = (12, 24, 60, 120, 240, 360)
GET_PAYLOADS = ("pools", "scenarios", "methodology", "model-quality", "health")
#: Client-side routes (web/src/routing.ts); each gets its own index.html so deep links load.
SITE_ROUTES = ("portfolio", "scenario-lab", "model-quality", "methodology")
PER_POOL = ("data_class", "notice", "pool_id", "as_of", "model", "assumptions")


def scenario_body(code: str) -> dict[str, Any]:
    """The API request body for a static scenario code."""
    if code == "flat":
        return {"kind": "flat"}
    if code.startswith("p") and code[1:].lstrip("-").isdigit():
        return {"kind": "parallel", "shock_bps": int(code[1:])}
    raise ValueError(f"not a static scenario code: {code!r}")


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False), encoding="utf-8")


def _canonical(payload: Any) -> Any:
    """JSON round trip, so stored and served values compare exactly."""
    return json.loads(json.dumps(payload, allow_nan=False))


def assemble(
    index: dict[str, Any],
    projections: dict[str, dict[str, Any]],
    pairs: dict[str, Any],
    pool_id: str,
    code_a: str,
    code_b: str,
    horizon: int,
) -> dict[str, Any]:
    """The API's projection response, rebuilt from the static files of one pool and horizon.

    ``projections`` maps scenario code to that scenario's projection file; ``pairs`` is the
    pool's pair file for ``horizon``.
    """

    def scenario_out(code: str) -> dict[str, Any]:
        stored = projections[code]
        at = stored["by_horizon"][str(horizon)]
        return {
            **stored["scenario"],
            "summary": at["summary"],
            "monthly": stored["monthly"][:horizon],
            "reliability": at["reliability"],
            "model_range": at["model_range"],
        }

    pair = pairs[f"{code_a}|{code_b}"]
    return {
        **index["pools"][pool_id],
        "a": scenario_out(code_a),
        "b": None if code_b == NO_COMPARISON else scenario_out(code_b),
        "a_minus_b": pair["a_minus_b"],
        "warnings": pair["warnings"],
    }


def export_static(
    bundle_dir: Path,
    out: Path,
    *,
    scenarios: tuple[str, ...] = STATIC_SCENARIOS,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict[str, Any]:
    """Write the static data tree for ``bundle_dir`` into ``out``; return the index.

    ``horizons`` must include the longest one served, whose monthly rows every shorter
    horizon slices.
    """
    from fastapi.testclient import TestClient  # dev dependency: export is a build step

    client = TestClient(create_app(bundle_dir, None, warm=False, rate_limit_per_minute=10**9))

    def get(name: str) -> Any:
        response = client.get(f"/api/{name}")
        response.raise_for_status()
        return response.json()

    def project(pool_id: str, code_a: str, code_b: str, horizon: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "pool_id": pool_id,
            "scenario": scenario_body(code_a),
            "horizon_months": horizon,
        }
        if code_b != NO_COMPARISON:
            body["compare_to"] = scenario_body(code_b)
        response = client.post("/api/project", json=body)
        response.raise_for_status()
        payload: dict[str, Any] = _canonical(response.json())
        return payload

    payloads = {name: get(name) for name in GET_PAYLOADS}
    payloads["health"]["project_latency_ms"] = None  # the export's own timings are meaningless
    payloads["health"]["cache_warm"] = True
    for name, payload in payloads.items():
        _write(out / "api" / f"{name}.json", payload)

    pool_ids = [pool["pool_id"] for pool in payloads["pools"]["pools"]]
    index: dict[str, Any] = {
        "format": STATIC_FORMAT,
        "bundle_digest": payloads["health"]["bundle_digest"],
        "scenarios": list(scenarios),
        "horizons": list(horizons),
        "credit": "defaults (the API's CreditIn defaults); other assumptions need the live API",
        "pools": {},
    }
    for pool_id in pool_ids:
        projections: dict[str, dict[str, Any]] = {}
        for horizon in horizons:
            pairs: dict[str, Any] = {}
            for code_a in scenarios:
                for code_b in (*scenarios, NO_COMPARISON):
                    response = project(pool_id, code_a, code_b, horizon)
                    common = {key: response[key] for key in PER_POOL}
                    if index["pools"].setdefault(pool_id, common) != common:
                        raise AssertionError(f"per-pool fields vary within {pool_id}")
                    pairs[f"{code_a}|{code_b}"] = {
                        "a_minus_b": response["a_minus_b"],
                        "warnings": response["warnings"],
                    }
                    a = response["a"]
                    stored = projections.setdefault(
                        code_a,
                        {
                            "scenario": {k: a[k] for k in ("kind", "shock_bps", "label")},
                            "monthly": [],
                            "by_horizon": {},
                        },
                    )
                    stored["by_horizon"][str(horizon)] = {
                        key: a[key] for key in ("summary", "reliability", "model_range")
                    }
                    if horizon == max(horizons):
                        stored["monthly"] = a["monthly"]
            _write(out / "pairs" / pool_id / f"{horizon}.json", pairs)
        for code, stored in projections.items():
            _write(out / "projections" / pool_id / f"{code}.json", stored)
    _write(out / "index.json", index)

    # Every response the grid covers must be rebuilt exactly from the written files. The API is
    # asked again (its projections are cached) so that responses need not be held in memory.
    for pool_id in pool_ids:
        stored = {
            code: json.loads((out / "projections" / pool_id / f"{code}.json").read_text("utf-8"))
            for code in scenarios
        }
        for horizon in horizons:
            pairs = json.loads((out / "pairs" / pool_id / f"{horizon}.json").read_text("utf-8"))
            for code_a in scenarios:
                for code_b in (*scenarios, NO_COMPARISON):
                    rebuilt = assemble(index, stored, pairs, pool_id, code_a, code_b, horizon)
                    if rebuilt != project(pool_id, code_a, code_b, horizon):
                        raise AssertionError(
                            f"static export differs from the API: {pool_id} {code_a} "
                            f"{code_b} {horizon}"
                        )
    return index


def build_site(
    bundle_dir: Path,
    web_dist: Path,
    out: Path,
    *,
    scenarios: tuple[str, ...] = STATIC_SCENARIOS,
    horizons: tuple[int, ...] = HORIZONS,
) -> dict[str, Any]:
    """A complete static site: the static web build, its data tree and an entry per route."""
    if not (web_dist / "index.html").is_file():
        raise FileNotFoundError(f"no static web build at {web_dist} (vite build --mode static)")
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(web_dist, out)
    index = export_static(bundle_dir, out / "data", scenarios=scenarios, horizons=horizons)
    page = (web_dist / "index.html").read_text(encoding="utf-8")
    for route in SITE_ROUTES:
        (out / route).mkdir()
        (out / route / "index.html").write_text(page, encoding="utf-8")
    (out / "404.html").write_text(page, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return index
