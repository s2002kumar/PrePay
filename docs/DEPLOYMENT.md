# Deploying the public demo

The deployable unit is one container. It serves the web UI and the API from the same origin,
using **fictional** pools and a **synthetic-trained** model built inside the image. Nothing in
it is Freddie Mac data, and the build context can't include `data/`, `artifacts/`, `notes/` or
`.git` (`.dockerignore` is an allowlist).

## Build and run locally

```bash
docker build -t prepay-demo .                               # ci preset: small synthetic world
docker build --build-arg DEMO_PRESET=dev -t prepay-demo .   # 8x larger world (README screenshots)
docker run --rm -p 8000:8000 prepay-demo                    # http://127.0.0.1:8000
```

**Which preset to deploy.** Use `dev` for a public demo. In that world the pre-registered rule
selects the spline logistic model (B2). In the small `ci` world it keeps the lookup table (B1),
whose coarse incentive bins give the same speed to every loan more than 100 bp out of the money
(VALIDATION_REPORT §5). The cost is build time: a `dev` build took 55 minutes on a laptop that
was also running heavy unrelated work, so treat that as an upper bound, not a benchmark. Uncached
B2 projections are also slower than B1's (2.4 s vs about 20 ms on the same loaded laptop). The
standard scenarios are precomputed at startup.

The build stages are:

1. **web:** `npm ci --ignore-scripts` and a production Vite build (no source maps).
2. **builder:** `prepay demo build` generates fictional data, then locks, ingests and transforms
   it with dbt, trains, seals, and evaluates the lockbox once. It then builds a runtime virtual
   environment with only the API dependencies.
3. **runtime:** Python slim plus that environment, the sealed bundle and the static UI. It runs
   as non-root user `prepay` (UID 10001) with a container `HEALTHCHECK` on `/api/health`.

Base images are pinned by digest. Bump them deliberately (Dependabot proposes updates).

## Runtime settings

| Variable | Default | Meaning |
|---|---|---|
| `PREPAY_RATE_LIMIT_PER_MINUTE` | 60 | Projection requests per client per minute (in-process) |

`prepay serve --proxy-headers` trusts `X-Forwarded-For`. Use it only behind a trusted reverse
proxy (as the image's default command assumes), so rate limiting keys on real client addresses.

Sizing: plan for 1 vCPU and **2 GB RAM** per instance. A warmed `dev` container measured 887 MiB
resident, which leaves too little headroom at 1 GB. The image is 913 MB: its runtime
environment carries the package's base dependencies (pyarrow, DuckDB, SciPy, scikit-learn),
which the API doesn't all need. Splitting them out is a known improvement. Startup precomputes the
standard scenarios in the background, and `/api/health` reports `cache_warm`.

## Before every public deploy

```bash
make publication-check          # tracked files, history, web build and demo bundle
docker build -t prepay-demo . && docker run --rm prepay-demo prepay --version
```

Confirm that the running app shows the fictional-data notice on every view, and that
`/api/health` reports `"artifact_class": "synthetic"`.

## Hosting (owner decision)

No hosting has been set up. Any hosted deploy needs the owner to choose a provider and approve
any account or cost. Options that run this container unchanged include Google Cloud Run, Fly.io,
Render and Hugging Face Spaces (Docker). Real-data models must never be deployed without a
separate license review (SOURCE_RESEARCH, ADR 0005).
