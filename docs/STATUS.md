# Prepay status and evidence ledger

Public, non-sensitive summary. Status levels: `NOT BUILT` · `IMPLEMENTED-SYNTHETIC` (works and is
tested on synthetic data only) · `VALIDATED-REAL-PRIVATE` (run privately on lawfully obtained
Freddie Mac files) · `PUBLIC-DEPLOYED` · `BLOCKED`. A green CI run is never a real-data claim.

Last updated: 2026-10-28.

## Blockers (owner action required)

| Blocker | Effect | Owner action |
|---|---|---|
| Freddie Mac terms review for publication | Real-data results stay private (not in this repository, CI or the demo) | Confirm the terms acceptance date and whether a noncommercial aggregate research report may be published |
| No code license selected | Repository is public but not open-source licensed | Choose a license (or none) |
| No hosting approved | P8 deployment / live demo | Approve a host (free tier or paid) |

## Real-data study (private)

The owner supplied the Freddie Mac SFLLD Standard sample (28 vintage archives, 1999–2026) on
2026-10-28. It is processed only on the owner's machine, outside cloud-synced folders. Raw files,
derived tables, trained models and real-data results never enter this repository, CI or the demo.
The study follows a pre-registered plan (ADR 0006). Its review packet is kept privately. Until the
owner completes a terms review, this file records only process status, never real-data numbers.

## Acceptance gates (SPEC §4)

| ID | Gate | Status | Evidence | Known gaps |
|---|---|---|---|---|
| P1 | Source schema + provenance | IMPLEMENTED-SYNTHETIC | `src/prepay/contracts/`, `src/prepay/ingest/`, ADR 0002, `tests/integration/test_ingest.py` | Layout header-verified against official files; data lock + checksums + byte-exact bronze lineage; pre-R47 fallback BLOCKED (no official layout artifact); real-file verification BLOCKED on data |
| P2 | Deterministic, idempotent pipelines | IMPLEMENTED-SYNTHETIC (ingest) | `test_rerun_reuses_outputs_and_detects_tampering`; byte-identical bronze on rerun | dbt/model stages not built yet |
| P3 | Point-in-time 3-state targets | IMPLEMENTED-SYNTHETIC | `transform/`, ADR 0003, `tests/integration/test_transform.py` (SQL = independent Python oracle; features reproduce generator truth < 1e-9; leakage/chronology guards proven to fail on corrupted data) | Real-data counts for date-mismatch and unexplained-end rules pending data |
| P4 | Reproducible trained models | IMPLEMENTED-SYNTHETIC | `src/prepay/modeling/`, ADR 0004, `tests/unit/test_models.py`, `tests/integration/test_modeling.py` | B0/B1/B2/M1 + calibration + run registry with digests on synthetic data only; drift (PSI), seed repeats, ablations and segment reports not built |
| P5 | Sealed future holdouts | IMPLEMENTED-SYNTHETIC (mechanism) | seal + one-shot lockbox; holdout guard tested with a reader spy; tamper and second-evaluation refusals tested | Real holdout evaluation BLOCKED on data |
| P6 | Cash-flow conventions + conservation | IMPLEMENTED-SYNTHETIC | `make test-finance`; ADR 0001; `docs/validation/FINANCE_ENGINE.md`; all twelve §6 items tested | Event-timing sensitivity not yet published |
| P7 | Pooled 12/24m backtests | IMPLEMENTED-SYNTHETIC | `src/prepay/evaluation/cohort.py` inside the lockbox; `docs/VALIDATION_REPORT.md` §5 | Real cohorts BLOCKED on data; count-weighted estimand; censoring assumed non-informative by the estimator |
| P8 | Interactive demo | IMPLEMENTED-SYNTHETIC (local + Docker) | `src/prepay/api/`, `web/`, ADR 0005; CI `e2e` job (Playwright + axe, 17 tests), `tests/integration/test_api.py` | Hosted deploy BLOCKED on hosting approval |
| P9 | Licensed-data boundary | IMPLEMENTED-SYNTHETIC | `prepay publication-check` (tracked set in `make check`; history + build outputs in CI `e2e`); synthetic-only bundle loader; allowlist `.dockerignore` | Manual license review needed before any real-data publication |
| P10 | README, reports, reproducible install | IMPLEMENTED-SYNTHETIC | README, VALIDATION_REPORT (real section BLOCKED), BENCHMARKS, review packets M2/M4/M5, Dockerfile | Clean-clone reproduction recorded in `docs/reviews/M5.md`; real results BLOCKED |

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M0 Foundations | IMPLEMENTED-SYNTHETIC | Includes the CI end-to-end path: synthetic ingest → dbt → trained model → finance projection (`test_end_to_end_model_hazards_drive_a_conserving_projection`) |
| M1 Ingest + provenance | IMPLEMENTED-SYNTHETIC | Streaming ZIP to bronze Parquet, data lock, FRED PMMS ingest + local fetch, per-field violation counts; real-data run BLOCKED on data |
| M2 Feature store | IMPLEMENTED-SYNTHETIC | dbt silver/gold + Python scenario feature state machine with exact historical parity; benchmark baseline in `docs/BENCHMARKS.md`; reviewer packet `docs/reviews/M2.md` |
| M3 ML | IMPLEMENTED-SYNTHETIC | Models, validation-only selection, cross-fitted calibration, seal/lockbox; trained only on synthetic data; real training BLOCKED on data |
| M4 Finance engine + freeze | IMPLEMENTED-SYNTHETIC | Engine, scenarios, pools, projection, seal/lockbox with cohort backtests; reviewer packet `docs/reviews/M4.md`; real freeze/holdout BLOCKED on data |
| M5 Product + publication | IMPLEMENTED-SYNTHETIC | API, web UI, publication gate, Docker image, security policy; reviewer packet `docs/reviews/M5.md`; hosted deploy BLOCKED on approval |

## Finance verification detail (FINANCIAL_CONVENTIONS §6)

| Item | Test | Status |
|---|---|---|
| 1 360-month amortization, 0/2/6/15% | `test_6_1_*` | pass |
| 2 Edge cases (n=1, tiny/high coupon, cents, zero balance) | `test_6_2_*` | pass |
| 3 Zero hazards = contractual | `test_6_3_*` (closed form + oracle) | pass |
| 4 Certain payoff / certain credit exit | `test_6_4_*` | pass |
| 5 Arbitrary simplex conservation | `test_6_5_*` (Hypothesis) | pass |
| 6 Recovery lag beyond horizon | `test_6_6_*` | pass |
| 7 Market shock leaves contractual flows unchanged | `test_6_7_rate_shock_with_fixed_hazards_leaves_contractual_flows_identical` | pass |
| 8 Lower payoff hazard lowers same-month payoff | `test_6_8_*` (Hypothesis) | pass |
| 9 Rep-line vs loan-level, ≥5 profiles | `test_6_9_*` (6 profiles) | pass; errors published in `docs/validation/FINANCE_ENGINE.md` |
| 10 Monte Carlo converges to expected ledger | `test_6_10_*` | pass |
| 11 PSA round trip | `test_6_11_*` | pass |
| 12 No rounding, no clipping | `test_6_12_*` | pass |
| Mutation kills | `test_mutation_kills.py` (8 mutants) | 8/8 killed |

## Reproduce

```bash
uv sync --frozen
make check          # or: uv run --frozen ruff check src tests && uv run --frozen mypy && uv run --frozen pytest
make test-finance
```

No independent human review has taken place; all reviews so far are agent self-review.
