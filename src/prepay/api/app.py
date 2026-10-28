"""FastAPI application serving the fictional demo (ARCHITECTURE §8).

The app loads only a verified synthetic demo bundle. It never opens ``data/``, raw files or a
real-trained run. The built web UI is served from the same origin, so no CORS is enabled.
"""

from __future__ import annotations

import collections
import contextlib
import os
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from prepay import __version__
from prepay.api.bundle import NOTICE, load_bundle
from prepay.api.methodology import methodology
from prepay.api.schemas import ErrorResponse, ProjectionRequest, ProjectionResponse
from prepay.api.service import ProjectionService, UnknownPoolError
from prepay.scenarios.rates import STANDARD_SCENARIOS, ScenarioError

MAX_BODY_BYTES = 32 * 1024
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)
DOCS_CSP = (
    "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
)


def error(
    status: int, code: str, message: str, details: list[dict[str, Any]] | None = None
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or []}}
    return JSONResponse(status_code=status, content=body)


class TokenBucket:
    """Per-client token bucket: ``per_minute`` requests, refilled continuously."""

    def __init__(self, per_minute: int) -> None:
        self.capacity = float(per_minute)
        self.rate = per_minute / 60.0
        self.state: dict[str, tuple[float, float]] = {}
        self.lock = threading.Lock()

    def allow(self, client: str) -> bool:
        now = time.monotonic()
        with self.lock:
            tokens, last = self.state.get(client, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens < 1.0:
                self.state[client] = (tokens, now)
                return False
            self.state[client] = (tokens - 1.0, now)
            if len(self.state) > 10_000:  # bound memory under many distinct clients
                self.state.clear()
            return True


class Guards(BaseHTTPMiddleware):
    """Security headers, body-size cap, rate limit on compute, latency sampling."""

    def __init__(
        self, app: Any, *, limiter: TokenBucket, latencies: collections.deque[float]
    ) -> None:
        super().__init__(app)
        self.limiter = limiter
        self.latencies = latencies

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        path = request.url.path
        if request.method in ("POST", "PUT", "PATCH"):
            declared = request.headers.get("content-length")
            if declared is not None and int(declared) > MAX_BODY_BYTES:
                return self._secure(
                    error(413, "payload_too_large", f"request body exceeds {MAX_BODY_BYTES} bytes"),
                    path,
                )
            if len(await request.body()) > MAX_BODY_BYTES:
                return self._secure(
                    error(413, "payload_too_large", f"request body exceeds {MAX_BODY_BYTES} bytes"),
                    path,
                )
        if path == "/api/project":
            client = request.client.host if request.client else "unknown"
            if not self.limiter.allow(client):
                limited = error(429, "rate_limited", "too many projection requests; retry soon")
                limited.headers["Retry-After"] = "5"
                return self._secure(limited, path)
        response = await call_next(request)
        if path == "/api/project":
            self.latencies.append((time.perf_counter() - started) * 1000.0)
        return self._secure(response, path)

    @staticmethod
    def _secure(response: Response, path: str) -> Response:
        response.headers["Content-Security-Policy"] = (
            DOCS_CSP if path.startswith("/api/docs") else CSP
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response


def create_app(
    bundle_dir: Path,
    static_dir: Path | None = None,
    *,
    warm: bool = True,
    rate_limit_per_minute: int | None = None,
) -> FastAPI:
    bundle = load_bundle(bundle_dir)
    service = ProjectionService(bundle)
    latencies: collections.deque[float] = collections.deque(maxlen=1000)
    per_minute = rate_limit_per_minute or int(os.environ.get("PREPAY_RATE_LIMIT_PER_MINUTE", "60"))

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if warm:
            threading.Thread(target=service.warm_cache, name="warm-cache", daemon=True).start()
        else:
            service.warm.set()
        yield

    app = FastAPI(
        title="Prepay demo API (fictional data)",
        version=__version__,
        description=NOTICE,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    )
    app.add_middleware(Guards, limiter=TokenBucket(per_minute), latencies=latencies)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", ())), "msg": str(e.get("msg", ""))} for e in exc.errors()
        ]
        return error(422, "invalid_request", "request failed validation", details)

    @app.exception_handler(ScenarioError)
    async def bad_scenario(_: Request, exc: ScenarioError) -> JSONResponse:
        return error(422, "invalid_scenario", str(exc))

    @app.exception_handler(UnknownPoolError)
    async def unknown_pool(_: Request, exc: UnknownPoolError) -> JSONResponse:
        return error(404, "unknown_pool", f"no fictional pool {exc.args[0]!r}")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, __: Exception) -> JSONResponse:
        return error(500, "internal_error", "unexpected error; no details are exposed")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        sample = np.array(latencies) if latencies else None
        return {
            "status": "ok",
            "version": __version__,
            "artifact_class": "synthetic",
            "data_class": "fictional",
            "model": service.model_name,
            "cache_warm": service.warm.is_set(),
            "bundle_digest": bundle.manifest["content_digest"],
            "project_latency_ms": None
            if sample is None
            else {
                "count": int(sample.size),
                "p50": float(np.percentile(sample, 50)),
                "p95": float(np.percentile(sample, 95)),
            },
        }

    @app.get("/api/pools")
    def pools() -> dict[str, Any]:
        return {"data_class": "fictional", "notice": NOTICE, "pools": service.pool_summaries()}

    @app.get("/api/pools/{pool_id}")
    def pool(pool_id: str) -> dict[str, Any]:
        if pool_id not in service.pools:
            raise UnknownPoolError(pool_id)
        return {
            "data_class": "fictional",
            "notice": NOTICE,
            "pool": service.pools[pool_id].summary(),
        }

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, Any]:
        last = service.bundle.rates
        return {
            "data_class": "fictional",
            "as_of_rate_30y_pct": float(last.rate_30y[-1]),
            "as_of_rate_15y_pct": float(last.rate_15y[-1]),
            "standard": [
                {"kind": s.kind, "shock_bps": s.shock_bps, "label": s.label}
                for s in STANDARD_SCENARIOS
            ],
        }

    @app.post("/api/project", response_model=ProjectionResponse)
    def project(request: ProjectionRequest) -> ProjectionResponse:
        return service.project(request)

    @app.get("/api/methodology")
    def method() -> dict[str, Any]:
        return methodology(service.model_name, service.bundle.run.manifest)

    @app.get("/api/model-quality")
    def model_quality() -> dict[str, Any]:
        return {"data_class": "fictional", **service.bundle.model_quality}

    if static_dir is not None and (static_dir / "index.html").is_file():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
        index = static_dir / "index.html"

        # Client-side routes all render index.html; hashed assets come only from the mount above.
        # No filesystem path is ever built from the request path.
        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path.startswith("api/"):
                return error(404, "not_found", "unknown API route")
            return FileResponse(index)

    return app


def app_from_env() -> FastAPI:
    """Factory for ``uvicorn prepay.api.app:app_from_env --factory``."""
    bundle = Path(os.environ.get("PREPAY_DEMO_BUNDLE", "build/demo"))
    static = os.environ.get("PREPAY_WEB_DIST", "web/dist")
    return create_app(bundle, Path(static) if static else None)
