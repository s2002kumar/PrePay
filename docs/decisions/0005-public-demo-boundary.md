# ADR 0005: Public demo boundary: synthetic bundle, strict API, single origin

- Status: accepted
- Date: 2026-10-28
- Scope: `src/prepay/api/`, demo deployment

## Context

SPEC §6 and ARCHITECTURE §8 require that the public service use only synthetic inputs and
artifacts, never load raw Freddie Mac files or restricted models, and label every output as
fictional. The demo still has to be genuinely interactive and fast enough to compare two
scenarios.

## Decisions

1. **One demo bundle, built from fictional data only.** `prepay demo build` runs the whole
   pipeline (generate → lock → ingest → dbt → train → seal → lockbox) on `prepay synth` data
   with anomalies off, then copies only the sealed run, its validation and holdout summaries, and
   the synthetic rate history.
2. **The loader refuses anything else.** Both the bundle and the run must be marked `synthetic`,
   the run's seal must verify, and the bundle's content digest must match. Otherwise the
   app doesn't start. Artifacts are JSON / LightGBM text, so loading can't execute code.
3. **Fictional pools are generated in code** from seeded distributions at startup. No pool row
   comes from any file.
4. **Strict, bounded contracts.** Pydantic models with `extra="forbid"`: horizon ≤ 360 months,
   shocks within ±500 bp, rates 0.5–20%, paths ≤ 360 values, pool IDs `^[a-z0-9-]{1,64}$`. Errors
   use one envelope `{error: {code, message, details}}` and never include tracebacks.
5. **Abuse limits without new infrastructure.** A 32 KiB body cap, an in-process per-client token
   bucket on `POST /api/project` (default 60/min), and an LRU cache keyed by the validated request.
   The standard scenarios are precomputed in a background thread at startup.
6. **Single origin, no CORS.** The built SPA is served by the same app. The CSP is
   `default-src 'self'`, with a relaxed policy only on `/api/docs` for the Swagger UI assets.
   Static serving refuses paths outside the build directory.
7. **Observability without user data.** Projection latency is sampled in memory (p50/p95 in
   `/api/health`). Logs carry aggregates only.

## Alternatives rejected

- Serving a real-data model behind a license flag. The terms don't allow it by default, and
  a runtime flag is too easy to flip.
- A separate API host with CORS. More configuration and attack surface for no user benefit.
- Redis or an external rate limiter. Not justified for a single small instance; revisit only
  with measured need.

## Consequences

The public demo can't show real-data results. The model-quality view states the real-data status
(blocked) and presents synthetic holdout metrics as an engineering demonstration.
