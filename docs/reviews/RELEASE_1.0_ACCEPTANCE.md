# Prepay 1.0 acceptance report

Prepared 2026-11-02 by the implementing agent. **Self-review, not independent review.**
Synthetic data only: nothing here measures real-world or commercial forecasting accuracy.

## Verdict

**Is the engineering product finished? Not yet released: one release-blocking defect
remains.**
- **Passed:** AC1–AC9, everything except public deployment. That covers the workflows,
  financial parity with the audited engine, UI, accessibility, performance, clarity, the
  data boundary, the clean-setup demonstration and the documentation.
- **Blocked:** AC10, public deployment. The static site is built on every push to `main`,
  checked against the API and the live app, and scanned by the publication gate. It can't be
  published until GitHub Pages is enabled on the repository. That one-time setting creates a
  public website, so it belongs to the owner, and the agent's permissions refused it.

Once Pages is enabled and the `pages` workflow re-runs, AC10 can be confirmed. Then nothing
listed here blocks release.

| | |
|---|---|
| Release-blocking defects | **1**: GitHub Pages not enabled (R1 below) |
| Criteria | AC1–AC9 **PASS** · AC10 **BLOCKED** (R1) |
| Known non-blocking limitations | 7 (below) |

## Scope

The owner's 2026-11-02 brief defines Prepay 1.0 as a polished, publicly accessible,
synthetic-only mortgage cash-flow product. A user must be able to:
1. choose a portfolio;
2. define rate scenarios;
3. estimate when principal returns;
4. compare forecasts;
5. see the assumptions and the reliability of what they read.

The real-data research and the prospective forward evaluation are maintained separately and
are not product criteria (ADR 0011).

## Criteria

| ID | Criterion | Result | Evidence |
|---|---|---|---|
| AC1 | **End-to-end scenario workflow.** Choose a pool, see its composition, project it, define two scenarios (preset, parallel or custom ramp in the live app; 13-scenario grid on the static site), pick a horizon, adjust credit assumptions (live app), share by URL | PASS | Playwright: `portfolio explorer hands a pool to the scenario lab`, `scenario lab compares two scenarios and keeps state in the URL`, `custom ramp scenario and assumptions drawer`, `every precomputed scenario loads…` (CI run [41485732409](https://github.com/s2002kumar/PrePay/actions/runs/41485732409): 25 passed) |
| AC2 | **Financial outputs equal the audited engine.** Every served monthly row is the engine's ledger; every summary number follows from the served rows | PASS | `tests/integration/test_api_finance_parity.py` checks 4 pools × flat, parallel and custom paths. Rows equal the engine ledger exactly. Horizon totals, 12/24-month and horizon fractions, the cumulative column, model CPR and full-life cash WAL are recomputed with plain arithmetic, to a relative 1e-12. The engine itself: exact rational and 60-digit Decimal oracles, 8/8 mutants killed, finance suite 97 passed at 95.6% branch coverage |
| AC3 | **The static site shows exactly what the API computes** | PASS | The export rebuilds all 4,368 grid responses from its files and requires exact equality with the API, or it fails. Playwright compares the static and live pages for 4 pool, scenario and horizon cases: tiles, comparison sentence, model strip, reliability table and the monthly ledger table, as identical text |
| AC4 | **Active model, assumptions, support warnings, meaningful comparisons are displayed** | PASS | The Scenario Lab shows a strip with the active model, the as-of rate, the credit-exit assumption and source, and the conventions. It adds a plain-language reading of B against A built only from the API's A−B deltas, an applicability verdict and model-family range per scenario, and warnings for out-of-support scenarios. Playwright: `the active model, its assumptions and each scenario's applicability are visible`; API: `test_api_reliability.py` (6 tests) |
| AC5 | **Responsive and accessible** | PASS | Playwright: no horizontal scroll at 375 px on every view. axe (WCAG 2.0/2.1 A and AA): no serious or critical violations on every view in light and dark mode, and on the static site. Charts are keyboard readable |
| AC6 | **Performant** | PASS | *Live API* (`prepay demo latency`, `dev` bundle with B2 served, GitHub runner, Pages run [41487102389](https://github.com/s2002kumar/PrePay/actions/runs/41487102389)): a cached two-scenario request takes p50 6.9 ms and p95 7.5 ms (30 requests); a cold request with two custom paths, projecting every model family, takes p50 7.3 s (6 requests); the standard scenarios warm in 54 s at startup; peak RSS is 1,148 MiB, inside the 2 GB sizing. *Static site:* JS 91 KB gzip; one projection fetches two scenario files and one pair file; no server compute. #30 removed duplicate projections, made categorical encoding output-identical and vectorized, and bounded the cache's per-result memory |
| AC7 | **Understandable** | PASS | Every displayed metric has a unit and a formula (Methodology page, `/api/methodology`). Explanations are in the [walkthrough](../WALKTHROUGH.md) and [How it works](../HOW_IT_WORKS.md). Fictional-data notice on every view (Playwright); data class and notice in API responses (`test_api.py`) |
| AC8 | **Synthetic-only boundary and security** | PASS | The bundle loader refuses non-synthetic or unsealed runs (`test_bundle_guards`). The publication gate covers tracked files, history, web build, demo bundle and the static site (CI `e2e`, `pages.yml`, `test_static_data_passes_the_publication_gate`). Also: CSP (header live, meta static), strict schemas, body cap, rate limit, CodeQL, SHA-pinned actions, read-only default token |
| AC9 | **Works from a clean setup** | PASS | Each CI run starts from a clean checkout and the lockfiles: `make setup` → `make check` (421 passed) → `make test-finance` → demo bundle → web build → static site → 25 browser tests. `docker.yml` builds the image from a clean context, waits for health and scans the image filesystem. Run [41487102350](https://github.com/s2002kumar/PrePay/actions/runs/41487102350) on `d4abb1d`: built in 3 min 40 s (`ci` preset), `/api/health` ok with `artifact_class: synthetic`, UI 200, image scan 0 findings |
| AC10 | **Deployed with no paid resources** | **BLOCKED** (R1); build and verification pass | `pages.yml` on `main`, run [41487102389](https://github.com/s2002kumar/PrePay/actions/runs/41487102389) on `d4abb1d`: build job **success**. It built the `dev` bundle (16.5 min), exported and verified all 4,368 responses (248 s), passed the 7 static-vs-live browser tests and the publication gate, and uploaded the 13 MB site. The deploy job failed with *"Ensure GitHub Pages has been enabled"* (R1). No paid service, account or secret is used |

Documentation, part of the brief:
- final [README](../../README.md);
- architecture explanation, [How it works](../HOW_IT_WORKS.md);
- recruiter [walkthrough](../WALKTHROUGH.md);
- [Deployment](../DEPLOYMENT.md);
- this report.

## What remains

### Release-blocking (1)

| # | Defect | Effect | Resolution |
|---|---|---|---|
| R1 | GitHub Pages is not enabled for the repository | The verified static site isn't published, so there is no public URL yet | **Owner:** Settings → Pages → Source: *GitHub Actions*, then re-run the latest `pages` workflow. Free for a public repository |

### Known limitations (not release-blocking)

| # | Limitation | Why it stands |
|---|---|---|
| L1 | The live container (custom paths, adjustable credit) isn't hosted publicly | Every host that runs it unchanged needs an owner account (DEPLOYMENT). It runs locally and in Docker with one command |
| L2 | The static site holds 13 scenarios at default credit assumptions | Precomputation trades breadth for a free, instant, server-less site (ADR 0011) |
| L3 | No code license chosen | Owner decision. The repository is public but not open-source licensed |
| L4 | No independent human review | All reviews, including this one, are agent self-review |
| L5 | Performance numbers come from shared CI runners and one laptop | Not a capacity benchmark. The container sizing guidance (DEPLOYMENT) is unchanged |
| L6 | In the live app, a comparison of two new custom paths takes about 7 s | Each uncached request projects 900 loans × about 370 months for every fitted model family, to show the model-family range. The UI keeps the previous result visible, dimmed, while it loads. Standard scenarios are cached (7 ms). The public static site is precomputed and unaffected |
| L7 | One open Dependabot alert: `minimatch` 10.2.6, [GHSA-g3hv-75wg-m249](https://github.com/advisories/GHSA-g3hv-75wg-m249), medium (denial of service from crafted glob patterns), fixed only in 11.0.1 | Development-only: pulled in by `eslint` and `typescript-eslint`, which accept only 10.x, and never fed untrusted patterns. Not in the shipped site's bundle. The engineering standard blocks known exploitable high or critical vulnerabilities. Dependabot's TypeScript 7 bump (#34) fails dependency resolution, because `typescript-eslint` supports TypeScript below 6.1, so it stays unmerged |

## Separate tracks (not product criteria)

- **Real-data research** stays private on the owner's machine. Its sealed study is unchanged.
  The selected model failed across rate regimes and is **not approved as a forecaster**.
- **R2 commitments and the prospective registration** ran on the owner's machine without
  restarting healthy work ([R2 report](R2_QUALITY_GATES.md) G10–G16):
  - DEV2017 and REFIT2026 are trained and sealed. REFIT2026's first attempt ran out of host
    memory, so it trained at 0.05 under the pre-registered memory ladder.
  - Both members passed implementation verification.
  - The forward comparison was registered on 2026-11-02, with only release 48 on disk, so
    registration preceded any forward data.
  - The opening's rehearsal completed, with a 2.0 GB peak.
  - Rolling-origin and stability runs are in progress, at low priority.
- **Research freeze:** no new model families, external economic data, experiments or
  infrastructure after R2 without a separate owner decision (ADR 0011).

## Reproduce

```bash
uv sync --frozen && make check && make test-finance                 # 421 + 97 tests, synthetic
make demo-bundle DEMO_PRESET=dev                                     # the public demo's world
(cd web && npm ci --ignore-scripts && npx vite build)
make static-site                                                     # verified static site
(cd web && PREPAY_STATIC_SITE=../build/pages-site npx playwright test --project desktop --project static)
uv run --frozen prepay demo latency --bundle build/demo              # latency and peak RSS
make demo                                                            # live app on :8000
```
