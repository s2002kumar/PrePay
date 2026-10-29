# Prepay status and evidence ledger

Public, non-sensitive summary. Status levels: `NOT BUILT` · `IMPLEMENTED-SYNTHETIC` (works and is
tested on synthetic data only) · `VALIDATED-REAL-PRIVATE` (run privately on lawfully obtained
Freddie Mac files) · `PUBLIC-DEPLOYED` · `BLOCKED`. A green CI run is never a real-data claim.

Last updated: 2026-10-29.

`VALIDATED-REAL-PRIVATE` means the stage was run and checked on the real files privately. It
records that the check ran, not that every result was favourable. Real-data outcomes, including
failed checks, are in the private review packet.

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

| Stage (ADR 0006) | Status | Date |
|---|---|---|
| Source verification: Release 48 layout, cutoff, archive integrity, data lock | done | 2026-10-28 |
| Full ingest and dbt build at sample scale; profile; rebuild determinism | done; real data exposed one non-deterministic mart, now fixed | 2026-10-28 |
| Independent label audit and feature parity | done; real data exposed one label bug (ADR 0003 amendment 1), now fixed and re-audited | 2026-10-28 |
| Training and validation-only selection (ADR 0004), reduced training fraction for memory (ADR 0006 §5) | done | 2026-10-29 |
| B1 incentive diagnosis on training and validation data (ADR 0007) | done before the seal | 2026-10-29 |
| Lockbox dress rehearsal on non-holdout data | done | 2026-10-29 |
| Seal, then the single lockbox opening (primary + pre-registered secondary analyses) | done, once | 2026-10-29 |
| Private review packet: verified evidence, failed checks, limitations, recommendations | written | 2026-10-29 |
| Independent review of the study | not done | — |

Not every pre-registered holdout check passed. The failures are reported in the private packet,
not repaired, and the sealed result is unchanged. Any revised model would be a separate experiment
evaluated only on reporting months after the Release 48 cutoff (ADR 0006 §11, ADR 0007, and the
proposed experiment in ADR 0008).

## Reliability program (started 2026-10-29)

`docs/RELIABILITY_PLAN.md` holds the ranked failure hypotheses, experiments and acceptance
criteria. Protocol: ADR 0009. Forward pre-registration: ADR 0010 (with ADR 0008). Prepay is **not
approved** as a reliable forecasting product. Every real-data step is run by the owner, and
real-data outputs aren't read by the agent (ADR 0009 §3).

| Item | Status | Evidence |
|---|---|---|
| Plan, ranked hypotheses, protocol (ADR 0009), forward pre-registration (ADR 0010) | accepted 2026-10-29 | `docs/RELIABILITY_PLAN.md`, `docs/decisions/0009-*`, `docs/decisions/0010-*` |
| Public rate-regime facts (§3.1) | built | `prepay diagnose rate-regimes`, `tests/unit/test_regimes.py`; run on FRED PMMS retrieved 2026-10-29 |
| Diagnostics D1–D8, candidates X1–X3 and H1, rolling origin V1, forward mechanism P1, safeguards R1–R3, finance F1–F3 | not built | — |

## Acceptance gates (SPEC §4)

| ID | Gate | Status | Evidence | Known gaps |
|---|---|---|---|---|
| P1 | Source schema + provenance | VALIDATED-REAL-PRIVATE | `src/prepay/contracts/`, `src/prepay/ingest/`, ADR 0002, `tests/integration/test_ingest.py`; Release 48 sample ingested privately 2026-10-28 | Freddie Mac publishes no archive checksums (integrity rests on ZIP CRCs, the data lock and layout checks); terms acceptance date to be recorded by the owner; pre-R47 fallback BLOCKED (no official layout artifact) |
| P2 | Deterministic, idempotent pipelines | VALIDATED-REAL-PRIVATE | Byte-identical bronze on rerun; `prepay fingerprint` (order-independent table hashes) with `tests/integration/test_audit.py`; two private full rebuilds compared | Timings on a shared laptop are upper bounds, not benchmarks |
| P3 | Point-in-time 3-state targets | VALIDATED-REAL-PRIVATE | `transform/`, ADR 0003 (+ amendment 1), `tests/integration/test_transform.py`; `prepay audit` (independent oracle vs dbt, feature parity) run privately | Oracle and SQL share one author (agent); a human spot-check of event labels is still needed |
| P4 | Reproducible trained models | VALIDATED-REAL-PRIVATE | `src/prepay/modeling/`, ADR 0004/0006, `tests/unit/test_models.py`, `tests/integration/test_modeling.py`; real run manifest records data, feature, software and Git digests | Reduced training fraction (memory rule, ADR 0006 §5); drift (PSI), seed repeats and ablations not built |
| P5 | Sealed future holdouts | VALIDATED-REAL-PRIVATE | seal + one-shot lockbox (tests: reader spy, tamper, second-evaluation refusal); real run sealed and opened once, 2026-10-29 | Not every pre-registered check passed (private packet). The test windows are now opened; a forward-evaluation path for later releases is not built |
| P6 | Cash-flow conventions + conservation | IMPLEMENTED-SYNTHETIC | `make test-finance`; ADR 0001; `docs/validation/FINANCE_ENGINE.md`; all twelve §6 items tested | Event-timing sensitivity not yet published |
| P7 | Pooled 12/24m backtests | VALIDATED-REAL-PRIVATE | `src/prepay/evaluation/cohort.py` (incidence + censoring bounds) and `runoff.py` (balance run-off) inside the lockbox; synthetic results in `docs/VALIDATION_REPORT.md` §5 | Real cohort and run-off results private; curtailments not modelled; interest, losses and recoveries not compared (no cash data) |
| P8 | Interactive demo | IMPLEMENTED-SYNTHETIC (local + Docker) | `src/prepay/api/`, `web/`, ADR 0005; CI `e2e` job (Playwright + axe, 17 tests), `tests/integration/test_api.py` | Hosted deploy BLOCKED on hosting approval |
| P9 | Licensed-data boundary | IMPLEMENTED-SYNTHETIC | `prepay publication-check` (tracked set in `make check`; history + build outputs in CI `e2e`); synthetic-only bundle loader; allowlist `.dockerignore` | Manual license review needed before any real-data publication |
| P10 | README, reports, reproducible install | IMPLEMENTED-SYNTHETIC | README, VALIDATION_REPORT, BENCHMARKS, review packets M2/M4/M5, Dockerfile; clean clone of `main` `f8ac9e2` in WSL2 Ubuntu: `make check` 275 passed, `make test-finance` 85 passed (95.60% finance coverage), 2026-10-28 | Real-data results private pending terms review |

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M0 Foundations | IMPLEMENTED-SYNTHETIC | Includes the CI end-to-end path: synthetic ingest → dbt → trained model → finance projection (`test_end_to_end_model_hazards_drive_a_conserving_projection`) |
| M1 Ingest + provenance | VALIDATED-REAL-PRIVATE | Streaming ZIP to bronze Parquet, data lock, FRED PMMS ingest + local fetch, per-field violation counts; release-cutoff check; run privately on the Release 48 sample |
| M2 Feature store | IMPLEMENTED-SYNTHETIC | dbt silver/gold + Python scenario feature state machine with exact historical parity; benchmark baseline in `docs/BENCHMARKS.md`; reviewer packet `docs/reviews/M2.md` |
| M3 ML | VALIDATED-REAL-PRIVATE | Models, validation-only selection, cross-fitted calibration, seal/lockbox, segment reports; trained, sealed and opened once on real data privately; results unpublished |
| M4 Finance engine + freeze | IMPLEMENTED-SYNTHETIC (engine) · VALIDATED-REAL-PRIVATE (freeze, run-off backtest) | Engine, scenarios, pools, projection; reviewer packet `docs/reviews/M4.md`; real freeze and run-off comparison done privately; engine outputs on real loans are not published |
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
