# Prepay — mortgage cash-flow modeling

**When will a mortgage pool return its principal if rates move?** Prepay models, month by month,
whether each fixed-rate loan pays off early, exits through a credit disposition, or stays
active. It then turns those probabilities into an audited cash-flow ledger for hypothetical
pools under interest-rate scenarios.

**ML and data engineering:** competing-risk modeling with LightGBM, logistic and
other baselines; point-in-time features, temporal validation, streaming ingest,
dbt transformations, and an auditable finance engine. The public model and
demo are synthetic. A separately evaluated real-data model did not pass
rate-regime checks, so this is **not a validated forecasting system**.

[![ci](https://github.com/s2002kumar/PrePay/actions/workflows/ci.yml/badge.svg)](https://github.com/s2002kumar/PrePay/actions/workflows/ci.yml)
[![pages](https://github.com/s2002kumar/PrePay/actions/workflows/pages.yml/badge.svg)](https://github.com/s2002kumar/PrePay/actions/workflows/pages.yml)

**Public demo: <https://s2002kumar.github.io/PrePay/>**. It shows fictional portfolios and a
synthetic-trained model. CI verifies the site against the API before each deploy and checks
the published site in a browser after it. Custom rate paths need the live app, which runs
locally (below). New here? Start with the [five-minute walkthrough](docs/WALKTHROUGH.md).

> **Prepay 1.0 (2026-11-02).** The [1.0 acceptance report](docs/reviews/RELEASE_1.0_ACCEPTANCE.md)
> records which criteria passed, the evidence for each, and what still blocks release.
> Public surfaces:
> - **The public demo** is a static GitHub Pages build. The real API computed every response,
>   and the build checked each one against it.
> - **The full app** (custom rate paths, adjustable credit assumptions) runs locally or in Docker
>   with one command.
>
> **Real-data research is separate and private.** The Freddie Mac sample was ingested, trained
> on and evaluated once on a sealed holdout. The selected model failed across rate regimes and
> is **not approved as a forecaster**; the results stay unpublished pending a terms review. A
> pre-registered forward test waits for months after 2026-06
> ([ADR 0010](docs/decisions/0010-forward-evaluation-preregistration.md)). Research is frozen
> after R2 ([ADR 0011](docs/decisions/0011-release-1-0-public-surface-and-scope-freeze.md)).
> **Nothing here claims real-world or commercial forecasting accuracy.** See
> [docs/STATUS.md](docs/STATUS.md).

![Scenario Lab comparing a flat rate path with a −100 bp shock for a fictional 2023 pool](docs/images/scenario-lab.png)

*Fictional pool, synthetic-trained model (`ci`-preset bundle; the public site uses the larger `dev` preset, so its numbers differ). Not a forecast of real mortgages.*

## Why it matters

A 30-year mortgage rarely lasts 30 years: borrowers move and refinance. For whoever holds the
loan, *when* principal comes back changes reinvestment risk, interest income and duration. If
payoff speed is underestimated after a rate drop, cash arrives years early and must be
reinvested at lower rates. If it's overestimated, capital stays locked in low-coupon loans.
Prepay makes that timing explicit, with every assumption labeled.

## What works today

| Capability | Status | Evidence |
|---|---|---|
| Source contract for Freddie Mac SFLLD Release 47/48 | implemented, header-verified against official files | [ADR 0002](docs/decisions/0002-sflld-source-contract.md) |
| Data lock, streaming ingest, byte-exact lineage | implemented on synthetic data | `tests/integration/test_ingest.py` |
| dbt silver/gold: quarantine, event labels, point-in-time features | implemented on synthetic data | [ADR 0003](docs/decisions/0003-event-labels-and-hazard-panel.md) |
| PSA, lookup, logistic and LightGBM competing-risk models | trained on synthetic data | [ADR 0004](docs/decisions/0004-model-protocol.md) |
| Sealed, one-shot holdout + censor-aware cohort backtest | implemented on synthetic data | [VALIDATION_REPORT](docs/VALIDATION_REPORT.md) |
| Audited cash-flow engine (Decimal oracle, mutation tests) | implemented | [FINANCE_ENGINE](docs/validation/FINANCE_ENGINE.md) |
| FastAPI + responsive web demo (fictional pools only) | implemented, runs locally and in Docker | [ADR 0005](docs/decisions/0005-public-demo-boundary.md) |
| Public static site: every response precomputed by the API and checked against it | live at <https://s2002kumar.github.io/PrePay/>; built, verified and deployed by `pages.yml` from `main`, then checked in a browser | [ADR 0011](docs/decisions/0011-release-1-0-public-surface-and-scope-freeze.md), [Deployment](docs/DEPLOYMENT.md) |
| Real-data training and validation | **run privately, unpublished** pending terms review; failed checks across rate regimes; not independently reviewed | [Runbook](docs/RESEARCH_RUNBOOK.md), [Status](docs/STATUS.md) |
| Failure diagnostics (era encoding, economic probes, support maps, stability) and constrained candidates (X1–X3, H1) | built and tested on synthetic data, with known-answer tests; real runs are owner-run | [Plan](docs/RELIABILITY_PLAN.md), [ADR 0009](docs/decisions/0009-reliability-program-protocol.md) |
| Forward evaluation on months nobody has seen | built; pre-registered; waits for a release with cutoff ≥ 2027-06 | [ADR 0010](docs/decisions/0010-forward-evaluation-preregistration.md) |
| Applicability verdict, model-family range and credit-as-assumption in every projection | implemented in the demo API and UI | [R1 packet](docs/reviews/R1.md) |
| Scenario Lab analytics interface: outcome first, cursor-linked inspector, full comparison table, support status ahead of every headline | implemented; every displayed number reconciled to the served JSON in browser tests; in owner review | [ADR 0012](docs/decisions/0012-scenario-lab-visual-system.md), [acceptance](docs/reviews/VISUAL_MILESTONE_ACCEPTANCE.md) |
| Hosted live container (custom paths online) | **not hosted**: every free container host needs an owner account | [Deployment](docs/DEPLOYMENT.md) |

## How it works

```mermaid
flowchart LR
  subgraph private[Private research: real data never leaves the machine]
    Z[Freddie Mac sample ZIPs] --> L[data lock<br/>SHA-256 + release]
    F[FRED PMMS rates] --> L
    L --> I[prepay ingest<br/>bronze Parquet + lineage]
    I --> D[dbt on DuckDB<br/>quarantine, events,<br/>features as of t-1]
    D --> M[prepay train<br/>B0 PSA · B1 lookup ·<br/>B2 logistic · M1 LightGBM]
    M --> S[seal → one-shot lockbox<br/>+ Aalen-Johansen run-off]
  end
  subgraph public[Public demo: fictional only]
    G[prepay synth<br/>synthetic world] --> B[same pipeline → sealed<br/>synthetic-trained bundle]
    B --> A[FastAPI] --> W[React UI]
    P[fictional pools] --> A
  end
  A -. scenario rates → features → hazards .-> E[finance engine<br/>audited ledger]
```

- **Labels** (MODELING §2): payoff = zero-balance code 01 not near maturity. Credit disposition
  = 02/03/09. Modification, whole-loan sale (15), RPL securitization (16) and defect (96)
  **censor**; they are never mislabeled as defaults. Data problems are quarantined and counted,
  never repaired.
- **No look-ahead:** every feature for month *t* uses information known at the end of *t−1*. A
  dbt test enforces it, a corrupted-warehouse test proves the test fails, and an independent
  Python state machine reproduces every feature exactly.
- **Honest evaluation:** models are tuned on 2018, calibrated on 2019, sealed, and opened once on
  2020+. The first report is immutable even when a baseline wins. In the small synthetic world
  it did: the parsimony rule kept the lookup table, which then lost to the logistic model. With
  8× the data the same rule picked the logistic model, which beat the other baselines on every
  holdout window. Both reports stand as written
  ([§5](docs/VALIDATION_REPORT.md#5-synthetic-study-results-engineering-demonstration)).
- **Money is conserved:** scheduled principal + payoffs + credit exits + remaining balance equals
  the starting balance every month. This is checked against a 60-digit Decimal oracle and by 8
  deliberate mutants that the tests must kill.

## Run it

Requirements: Python 3.12 via [uv](https://docs.astral.sh/uv/), Node 24, and GNU make (Linux,
macOS or WSL2). On Windows without make, run the `uv run ...` commands from the `Makefile`
directly.

```bash
make setup                 # uv sync --frozen
make check                 # ruff, mypy --strict, sqlfluff, all Python tests (synthetic, offline)
make demo-bundle           # fictional pipeline end to end -> build/demo (~3 min)
                           # DEMO_PRESET=dev: 8x larger world, as in the screenshots
(cd web && npm ci --ignore-scripts && npm run build)
make demo                  # http://127.0.0.1:8000
```

Or `docker build -t prepay-demo . && docker run --rm -p 8000:8000 prepay-demo`.

The public static site is built from the same bundle: `make static-site` (needs `make
demo-bundle` first), then serve it with `python -m http.server -d build/pages-site` and open
<http://127.0.0.1:8000/PrePay/>.

Other useful targets: `make synthetic-study` (full research pipeline through the lockbox on
fictional data), `make benchmark` (wall time / peak RSS per stage), `make publication-check`,
`make test-finance`. Real data: see the [private research runbook](docs/RESEARCH_RUNBOOK.md).

## Repository map

| Path | Contents |
|---|---|
| `src/prepay/finance/` | pure cash-flow engine, rates/PSA, WAL, Monte Carlo, rep lines |
| `src/prepay/contracts/`, `ingest/` | verified source layout, data lock, streaming bronze ingest |
| `transform/` | dbt project (staging → intermediate → marts) with data tests |
| `src/prepay/features/` | feature contract, scenario state machine, panel reader |
| `src/prepay/modeling/`, `evaluation/` | models, metrics, selection, seal/lockbox, cohort backtest |
| `src/prepay/scenarios/`, `api/` | rate scenarios, fictional pools, projection, FastAPI service, static export |
| `src/prepay/synthetic/` | seeded synthetic SFLLD-format world with known ground truth |
| `web/` | React UI, Playwright E2E + axe accessibility tests |
| `docs/` | specification, ADRs, status, validation, benchmarks, review packets |

## Evidence and engineering standards

CI runs on every PR: lint, strict typing, 400+ Python tests, a finance coverage gate (≥90%), web
lint/typecheck/tests, Playwright E2E with axe (WCAG 2.1 AA) on every view in light and dark, a
static-site build whose pages must show exactly the live app's numbers, and a publication gate
over history and build outputs. How the pieces fit: [How it works](docs/HOW_IT_WORKS.md). CodeQL, Dependabot and secret scanning are on,
and `main` requires all checks. Measured baseline: [BENCHMARKS](docs/BENCHMARKS.md). Reviewer
packets: [M2](docs/reviews/M2.md), [M4](docs/reviews/M4.md), [M5](docs/reviews/M5.md),
[R1 reliability](docs/reviews/R1.md), [R2 quality gates](docs/reviews/R2_QUALITY_GATES.md),
[1.0 acceptance](docs/reviews/RELEASE_1.0_ACCEPTANCE.md). All
reviews so far are self-review by the implementing agent; **no independent review has
happened.**

## Limitations

Synthetic results show that the software works, not that it predicts real mortgages. It is not
an MBS waterfall, a valuation or OAS tool, or lending/investment advice. It doesn't model
curtailments ([feasibility study](docs/validation/CURTAILMENTS.md)), delinquency cash timing or
servicing. Credit exits are a stated assumption unless the credit hazard is validated. Credit severity and recovery lag are
illustrative inputs. See the [validation report](docs/VALIDATION_REPORT.md) §8.

## Data and license

Real data: [Freddie Mac Single-Family Loan-Level Dataset](https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset)
(registration required, [terms](https://capitalmarkets.freddiemac.com/crt/docs/pdfs/fre_terms_conditions_sflld.pdf)).
No loan files, derived rows or real-trained models are in this repository or the demo. Rates:
FRED [MORTGAGE30US](https://fred.stlouisfed.org/series/MORTGAGE30US) /
[MORTGAGE15US](https://fred.stlouisfed.org/series/MORTGAGE15US).

**Code license: none selected yet.** The repository is public for review, but no open-source
license has been granted. That is the owner's decision.
