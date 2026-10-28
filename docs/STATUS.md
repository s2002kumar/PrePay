# Prepay status and evidence ledger

Public, non-sensitive summary. Status levels: `NOT BUILT` · `IMPLEMENTED-SYNTHETIC` (works and is
tested on synthetic data only) · `VALIDATED-REAL-PRIVATE` (run privately on lawfully obtained
Freddie Mac files) · `PUBLIC-DEPLOYED` · `BLOCKED`. A green CI run is never a real-data claim.

Last updated: 2026-10-28.

## Blockers (owner action required)

| Blocker | Effect | Owner action |
|---|---|---|
| No Freddie Mac SFLLD files on the build machine | All `VALIDATED-REAL-PRIVATE` work (P1 real schema check, P5 holdouts, P7 backtests, real metrics) | Register at Freddie Mac Clarity, download the Standard **sample** files (`sample_YYYY.zip`) locally |
| No code license selected | Repository is public but not open-source licensed | Choose a license (or none) |
| No hosting approved | P8 deployment / live demo | Approve a host (free tier or paid) |

## Acceptance gates (SPEC §4)

| ID | Gate | Status | Evidence | Known gaps |
|---|---|---|---|---|
| P1 | Source schema + provenance | IMPLEMENTED-SYNTHETIC | `src/prepay/contracts/`, `src/prepay/ingest/`, ADR 0002, `tests/integration/test_ingest.py` | Layout header-verified against official files; data lock + checksums + byte-exact bronze lineage; pre-R47 fallback BLOCKED (no official layout artifact); real-file verification BLOCKED on data |
| P2 | Deterministic, idempotent pipelines | IMPLEMENTED-SYNTHETIC (ingest) | `test_rerun_reuses_outputs_and_detects_tampering`; byte-identical bronze on rerun | dbt/model stages not built yet |
| P3 | Point-in-time 3-state targets | IMPLEMENTED-SYNTHETIC | `transform/`, ADR 0003, `tests/integration/test_transform.py` (SQL = independent Python oracle; features reproduce generator truth < 1e-9; leakage/chronology guards proven to fail on corrupted data) | Real-data counts for date-mismatch and unexplained-end rules pending data |
| P4 | Reproducible trained models | NOT BUILT | — | — |
| P5 | Sealed future holdouts | NOT BUILT | — | Real holdouts blocked on data |
| P6 | Cash-flow conventions + conservation | IMPLEMENTED-SYNTHETIC (partial) | `make test-finance`; ADR 0001 | §6.7 rate-shock invariance awaits the scenario layer; §6.9 rep-line error table not yet published |
| P7 | Pooled 12/24m backtests | NOT BUILT | — | Blocked on data for real cohorts |
| P8 | Interactive demo | NOT BUILT | — | Hosting not approved |
| P9 | Licensed-data boundary | NOT BUILT | — | — |
| P10 | README, reports, reproducible install | NOT BUILT | — | — |

## Milestones

| Milestone | Status | Notes |
|---|---|---|
| M0 Foundations | IN PROGRESS | Tooling, CI, finance core with oracle, source contract, synthetic generator (`docs/SYNTHETIC_DATA.md`); remaining: end-to-end CI path through a simple model + finance projection (lands with M3) |
| M1 Ingest + provenance | IMPLEMENTED-SYNTHETIC | Streaming ZIP to bronze Parquet, data lock, FRED PMMS ingest + local fetch, per-field violation counts; real-data run BLOCKED on data |
| M2 Feature store | IMPLEMENTED-SYNTHETIC | dbt silver/gold + Python scenario feature state machine with exact historical parity; benchmark baseline in `docs/BENCHMARKS.md`; reviewer packet `docs/reviews/M2.md` |
| M3 ML | NOT BUILT | |
| M4 Finance engine + freeze | NOT BUILT | Engine core exists (see P6); cohort study and sealing not built |
| M5 Product + publication | NOT BUILT | |

## Finance verification detail (FINANCIAL_CONVENTIONS §6)

| Item | Test | Status |
|---|---|---|
| 1 360-month amortization, 0/2/6/15% | `test_6_1_*` | pass |
| 2 Edge cases (n=1, tiny/high coupon, cents, zero balance) | `test_6_2_*` | pass |
| 3 Zero hazards = contractual | `test_6_3_*` (closed form + oracle) | pass |
| 4 Certain payoff / certain credit exit | `test_6_4_*` | pass |
| 5 Arbitrary simplex conservation | `test_6_5_*` (Hypothesis) | pass |
| 6 Recovery lag beyond horizon | `test_6_6_*` | pass |
| 7 Market shock leaves contractual flows unchanged | — | NOT BUILT (scenario layer) |
| 8 Lower payoff hazard lowers same-month payoff | `test_6_8_*` (Hypothesis) | pass |
| 9 Rep-line vs loan-level, ≥5 profiles | `test_6_9_*` (6 profiles) | pass; error table pending publication |
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
