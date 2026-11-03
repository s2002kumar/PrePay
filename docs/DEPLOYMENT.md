# Deploying the public demo

Prepay 1.0 has two public surfaces built from the same synthetic bundle (ADR 0011):

| Surface | Where | What it can do |
|---|---|---|
| Static site | GitHub Pages, <https://s2002kumar.github.io/PrePay/>; built, verified, deployed and re-checked by `pages.yml` on every push to `main` | precomputed responses: 4 pools × 13 scenarios (flat, ±50…±300 bp) × every comparison × 6 horizons, default credit assumptions |
| Live container | locally (`make demo` or Docker); no public host yet | any flat, parallel or custom path; adjustable credit assumptions |

## Static site (GitHub Pages)

```bash
make demo-bundle DEMO_PRESET=dev            # the public demo's synthetic world
(cd web && npm ci --ignore-scripts && npx vite build)   # live build, for the parity tests
make static-site                            # -> build/pages-site/PrePay/
python -m http.server 8080 -d build/pages-site          # http://127.0.0.1:8080/PrePay/
```

`prepay demo static-site` works in four steps:
1. It asks the API, through a test client on the bundle, for every response on the grid.
2. It stores each scenario's ledger once.
3. It rebuilds every covered response from the written files, and fails unless each one equals
   the API's response exactly.
4. It copies the static web build (`vite build --mode static`, base `/PrePay/`). It adds an
   `index.html` per route so that deep links load, plus a `404.html`.

The static build carries its Content-Security-Policy as a meta tag, because Pages can't set
headers.

Before each deploy, `pages.yml` runs Playwright against the site:
- for four pool, scenario and horizon cases, the site must show exactly what the live app
  shows: tiles, the comparison sentence, the reliability table and the monthly ledger table;
- every grid scenario must load;
- deep links must return 200;
- axe must report no serious violations.

The publication gate then scans the site. Only the deploy job has `pages: write` and
`id-token: write`.

After the deploy, the `verify` job runs the same browser checks against the published URL,
except parity with the live app, which needs the API (`playwright test --project deployed`
with `PREPAY_DEPLOYED_URL`). Pages is set to deploy from **GitHub Actions** (Settings → Pages), a
one-time repository setting.

## Live container

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
resident, which leaves too little headroom at 1 GB. With 1.0 (`prepay demo latency` on a GitHub
runner, `dev` bundle), peak RSS was 1,148 MiB after warming and 36 requests. The image is 913 MB: its runtime
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

## Hosting the live container (owner decision)

The static site is the public surface. The container isn't hosted, because every host that runs
it unchanged needs an account the owner must create:
- Hugging Face Spaces (Docker; its free CPU tier fits the 2 GB sizing);
- Google Cloud Run (needs a billing account);
- Fly.io;
- Render (its free 512 MB tier is below the container's footprint).

No paid resource is used without the owner's authorization. Real-data models must never be
deployed without a separate license review (SOURCE_RESEARCH, ADR 0005).
