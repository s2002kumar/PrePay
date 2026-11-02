"""Measure the demo API as a user meets it: request validation, projection and JSON (DEPLOYMENT).

Cold requests compare two custom ramps that no cache holds (every model family is projected for
the model range); warm requests repeat one standard comparison. Peak RSS is read after warming
the standard scenarios, which is the container's steady state before custom traffic.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

from prepay.api.app import create_app
from prepay.resources import peak_rss_bytes


def _summary(samples_ms: list[float]) -> dict[str, float]:
    ordered = sorted(samples_ms)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {
        "count": len(ordered),
        "p50_ms": round(statistics.median(ordered), 1),
        "p95_ms": round(p95, 1),
        "max_ms": round(ordered[-1], 1),
    }


def measure_latency(bundle_dir: Path, *, cold: int = 6, warm: int = 30) -> dict[str, Any]:
    from fastapi.testclient import TestClient  # dev dependency: a measurement tool

    app = create_app(bundle_dir, None, warm=False, rate_limit_per_minute=10**6)
    client = TestClient(app)
    started = time.perf_counter()
    app.state.service.warm_cache()
    warm_seconds = time.perf_counter() - started

    def timed(body: dict[str, Any]) -> float:
        t = time.perf_counter()
        response = client.post("/api/project", json=body)
        response.raise_for_status()
        return (time.perf_counter() - t) * 1000.0

    pool = "fictional-2023-high-coupon"
    cold_ms = [
        timed(
            {
                "pool_id": pool,
                "scenario": {"kind": "custom", "path_30y_pct": [5.0 - 0.05 * k] * 12},
                "compare_to": {"kind": "custom", "path_30y_pct": [7.0 + 0.05 * k] * 12},
                "horizon_months": 120,
            }
        )
        for k in range(cold)
    ]
    standard = {
        "pool_id": pool,
        "scenario": {"kind": "flat"},
        "compare_to": {"kind": "parallel", "shock_bps": -100},
        "horizon_months": 120,
    }
    warm_ms = [timed(standard) for _ in range(warm)]
    return {
        "model": client.get("/api/health").json()["model"],
        "warm_cache_seconds": round(warm_seconds, 1),
        "cold_two_scenario_request": _summary(cold_ms),
        "cached_two_scenario_request": _summary(warm_ms),
        "peak_rss_mib": round(peak_rss_bytes() / 2**20),
    }
