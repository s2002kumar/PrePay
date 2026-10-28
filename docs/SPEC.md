# Prepay | Product and delivery specification

Version 2.0 • 2026-10-27 • **implementation blueprint, not completed software**

## 1. One-sentence contract

Build a usable mortgage cash-flow intelligence **research tool** that reconstructs loan histories reproducibly, trains and independently validates probabilistic early-payoff models, and converts those probabilities into transparent, mathematically audited projections for hypothetical fixed-rate mortgage pools.

## 2. Personas and product screens

**Mortgage portfolio analyst:** selects a realistic *synthetic* 2021 low-coupon versus 2023 higher-coupon fictional pool, asks how much principal could be returned each month, and compares flat-rate, -100/-200 bp, and +100/+200 bp scenarios.

**Model risk/ML reviewer:** checks data provenance, label taxonomy, temporal splits, calibration, uncertainty, baselines, historical results, feature drift, limitations and whether the model is actually better than a simpler method.

**Engineering reviewer:** clones repo and runs deterministic CI using synthetic data; given separately and lawfully obtained real input files, reruns the local-only research pipeline to the same artifacts.

Required demo views: (a) Portfolio Explorer with coupon, age, balance, term and composition; (b) Scenario Lab with CPR/prepayment path, scheduled principal, illustrative contractual interest, modeled remaining UPB, cumulative principal return and weighted-average life; (c) Model Quality with approved aggregate validation metrics and known limitations; (d) Methodology/lineage/status.

Include clear **synthetic illustration** markings in every public portfolio, chart, API response, screenshot and export. No invented historical metrics, baseless confidence scores or trading advice.

## 3. What v1 models and what it does not

### In
- Freddie Mac *Standard Dataset sample*, fixed-rate fully amortizing US loans; verify exact originating vintage coverage and pinned cutoff after lawful download. Sample is approximately 50,000 loans per full vintage year, smaller for partial years. Treat sample as a sample of that product population, not the whole US market.
- Local historical analysis of **early voluntary payoff**, **terminal credit disposition** and **continuation** as competing next-month outcomes, with explicit censoring and modifications.
- Loan origination characteristics, prior-period state, and lagged PMMS rates; no future borrower behavior/features.
- Strong simple baseline, multinomial logistic, and a gradient-boosted model. Transparent model selection and optional calibration.
- Clear reproducible full-pool contractual amortization and **illustrative** payoffs/recoveries/interest, with loan-level vs aggregated approximation testing.
- Rate scenarios, out-of-time evaluation, data quality, monitoring, sensitivity, reproducible artifacts and a synthetic online sandbox.

### Out
- Loan modifications represented as defaults; 90+ delinquency represented as realized default losses; whole-loan sales represented as credit defaults.
- Actual servicing collections on delinquent loans, delinquency transitions, realized distressed interest accrual, complete credit-loss severity/cure models, curtailments, MI waterfall, MBS pass-through waterfall, fees, bond pricing/OAS or investment recommendations.
- Canadian mortgage calibration, adjustable-rate loans, production lending decisions, real-time scoring, hosted research data or public serving of real-trained models without a specific license approval.
- LLM wrapper. Focus is traditional trained ML, deterministic finance, and excellent DE.

## 4. Acceptance: quality over forced victories

A release is **honest and complete** if the criteria below are met. It is **not** conditional on fabricating a GBM win; if the GBM loses to a baseline, ship the stronger validated model and document why.

| ID | Gate | Evidence |
|---|---|---|
| P1 | Source schema and release are verified against downloaded files and Freddie documentation; complete row and file provenance | schema contract, checksums, data quality report |
| P2 | Deterministic pipelines are restartable, incremental by immutable input fingerprint, and idempotent | replay/test run, manifest comparison |
| P3 | Temporal point-in-time safe 3-state targets plus separately documented censor/other exits | event ledger, mapping tests, chronology tests |
| P4 | Reproducible trained models: ≥2 nontrivial baselines, GBM candidate, calibration, probability simplex | run registry, metrics, serialized preprocessing |
| P5 | Future holdouts scored without tuning after sealed candidate; report failures and intervals | frozen manifest, immutable evaluation outputs |
| P6 | Cash-flow units, monthly conventions, ledger conservation and end-of-term outcomes tested | independent oracle, property/metamorphic tests |
| P7 | Validated pooled backtests at 12/24 months where mature and censor-adjusted | independent cohort report plus limitations |
| P8 | Demo genuinely interactive, fast, clean and mobile-responsive, with rate scenarios and explainable economic effects | API tests, UI browser tests, deployment health checks |
| P9 | Licensed-data boundary verified; no real loan-level data or derivatives published by default | deployment manifest, history/asset scan, manual release gate |
| P10 | Clear README, method paper, validation report, reproducible install and actual results | docs and clean-machine smoke test |

Targets for model performance are chosen on validation data, registered **before** opening test data. Report whether actual targets were met; nonachievement is not grounds to alter the first holdout report. Test integrity is more important than a metric claim.

## 5. Implementation milestones and objective done states

**M0 — Foundations:** Python 3.12/uv, typed modules, ruff, mypy, pytest, Hypothesis, SQL lint/style, dbt-duckdb, Actions CI, configs, structured logs, independent seeded synthetic data generator with scenario ground truths, make targets, markdown docs. CI checks end-to-end *synthetic* ingest + simple model + finance projection, independent of internet and credentials.

**M1 — Data ingest and provenance:** official Release 47 *schema adapter* and fallback for a separately proven earlier release; raw zips validated in streaming mode, row counts, nonmatching key rates, duplicate/gap reports, immutable bronze Parquet by vintage, schema version tests, FRED snapshots and source-date metadata, checksum lock and atomic writes. Release adapter must follow actual official layout; **do not guess file positions**. Dataset license/access must be obtained outside of any unrestricted public download path.

**M2 — Contract-compliant feature store:** dbt sources/staging/marts, origination keys, monthly states, terminal events, right-censor reasons, at-risk exposure, features as-of t-1, unknown sentinels and masks, stable loan-month grain, calendar dimensions, public-safe aggregates separately. Include tests for histories, missing months, dates, code precedence, information cutoff, and parity of historical vs scenario feature logic.

**M3 — ML:** benchmark PSA, incentive/age lookup baseline and multinomial logistic; train GBM candidate(s), calibrate if justified, check high-class imbalance, reliability, drift, seed repeats, ablations, feature stability, time-window results, artifacts and probability coherence. Long data panels are read in bounded partitions; do not require unbounded Pandas load.

**M4 — Financial engine + freeze:** independently test amortization, monthly scheduled principal, full payoff, credit exit exposure, recovery lag/credit assumptions, maturity, weighted average life and no-money-from-nowhere checks; run predictive cohort study using **later-month** outcomes; freeze thresholds, configs, code/data/model digests; open holdouts once and permanently preserve the first results (no retroactive claim repair).

**M5 — Product + publication:** working FastAPI endpoints for fictional pools only, documented JSON schemas, input validation, caching/rate limits, typed errors, tests, polished UX, responsive comparison plots, provenance/method screens, official limitations and at-least-one deployment. The public service uses synthetic inputs/artifacts and cannot load raw Freddie files or restricted model artifacts. Release a transparent research report only if its dissemination is permitted.

**No forced milestone approvals:** Claude implements and merges under the runbook's safety rules without waiting after every small PR. Only explicit blocked decisions require the owner's help (data registration, license approval, secrets/paid resources, destructive operations or public visibility decisions). Every unblocked milestone proceeds automatically.

## 6. Repository visibility and public execution boundary

The owner explicitly chose a **public** GitHub repository for this project as of 2026-10-27. All source code, synthetic fixtures, architectural documentation, test harnesses, and synthetic demo assets are intended to be openly reviewable. Real Freddie Mac files, loan-level records, restricted model weights/derivatives, private research reports, secrets, and temporary work products remain local and untracked. Run public CI only on synthetic fixtures; a green public CI result does not claim trained real-data accuracy. Any publication of historical results requires a separate terms/licensing review.

## 7. Risks, explicit mitigations

| Risk | Mandatory response |
|---|---|
| Data not yet available through account registration | Finish synthetic runnable system; mark *real-world results pending data*, do not invent them |
| July 2026 schema evolution, incomplete quarters | pin actual release and schema, mismatch stops pipeline; compare `layout` and `disclosure changes` |
| Training months exceed RAM | streaming ingest, DuckDB range scans, partitioned Parquet; benchmark and document dataset sizes; loan-consistent sampling only if needed, with inclusion weights |
| Informative censorship by modification / note sales | separate exit taxonomy, sensitivity analysis, explicit Aalen-Johansen/IPCW limitations |
| Historical rate foresight | show hindsight-rate diagnostics separately from flat-as-of scenario runs |
| Credit dispositions vs delinquency/collections | describe credit event exactly; don't claim actual liquidations or realized cash yields are modeled |
| Distinct mortgage rates, structural breaks | flag PMMS November 17 2022; report shift and cohorts |
| Legal disclosure restrictions | public synthetic demo by default; approval needed for public trained artifacts and real-data derivatives |
| Impressive UI hiding weak model | always show baselines, fail cases, expected vs realized paths, and uncertainty |

## 7. Definition of finished

All 10 acceptance gates have recorded PASS/FAIL evidence; unresolved FAILs are explicitly surfaced and deployment limited appropriately. A live demo and private-reproducible real historical validation are both required for the *full flagship* claim. Without the real research data, a polished synthetic demo is a working **partial project**, not proof of predictive accuracy.
