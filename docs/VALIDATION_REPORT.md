# Prepay validation report

Structure follows MODELING §10. OSFI E-23 and US SR 26-2 were used as design inspiration only;
this is not a compliance attestation. **No independent validation has taken place.**

> **Status: the real-data study was run privately and is unpublished.** The owner supplied the
> Freddie Mac SFLLD Release 48 Standard sample on 2026-10-28. It was ingested, audited, trained
> on, sealed and evaluated once under ADR 0006, on the owner's machine. Its results, including
> pre-registered checks that failed, are in a private review packet until the owner completes a
> review of the dataset terms (ADR 0006 §3).
>
> Every number below comes from the *fictional* `ci` synthetic dataset. Those numbers show the
> pipeline, controls and reporting working end to end. They say **nothing** about predictive
> accuracy on real mortgages.

## 1. Intended use

A research tool that estimates monthly competing-risk probabilities (full voluntary payoff,
terminal credit disposition, remain active) for eligible fixed-rate Freddie Mac Standard-sample
loans, and turns them into transparent, assumption-labeled principal cash-flow projections for
hypothetical pools under rate scenarios. It isn't for lending decisions, security valuation,
trading or mapping to Freddie Mac securities (dataset terms).

## 2. Data, coverage and provenance

| Item | Real data | Synthetic study |
|---|---|---|
| Source | SFLLD Standard sample, Release 47/48 layout (ADR 0002) | `prepay synth --preset ci` (seed 20261028) |
| Coverage | Release 48 sample, vintages 1999–2026, cutoff 2026-06; counts private | 5,875 loans, vintages 2003–2026, cutoff 2026-06 |
| Provenance | data lock + bronze lineage (`_source_file`, `_source_row`) | same code path |
| Quality | `agg_data_quality` counts | 187 quarantined loans = exactly the injected anomalies |

## 3. Events, censoring and population (ADR 0003)

P = code 01 more than 2 months before maturity; C = 02/03/09; censoring at the first `Y`
modification and at 15/16/96; maturity is excluded; administrative censoring at the cutoff.
Censoring by modification, sale and disaster programs is **informative**, so cohort incidence
estimates carry that caveat.

## 4. Methodology (ADR 0004)

B0 PSA, B1 lookup, B2 spline logistic and M1 LightGBM softmax, trained on outcomes through
2017-12. Tuning and selection use 2018; calibration is decided on 2019 (cross-fitted). The run
is sealed before the one-shot 2020–2021, 2022–2023 and 2024-cutoff holdouts are opened.

## 5. Synthetic study results (engineering demonstration)

Two synthetic worlds were run through the full protocol, each with its own seal and one-shot
lockbox. Neither report was edited after opening. The small world (§5.1) is what CI and
`make synthetic-study` use. The larger world (§5.2) has 8× the loans and no injected anomalies;
it trains the model that the demo screenshots show.

### 5.1 Small world (`ci` preset, ~6k loans)

Reproduce with `make synthetic-study`; the report lands in
`data/synthetic/study/runs/<run>/evaluations/first.json`.

**Selection (validation A log loss):** B2 0.02625, M1 0.02640, B1 0.02687. The pre-registered
parsimony rule selected **B1**: B2's advantage was not significant on 79 validation events.
Calibration was **not** adopted (the cross-fitted temperature worsened one fold).

**Sealed holdout, one-step log loss** (lower is better):

| Window | Rows | Payoffs / credit | Selected (B1) | B2 | M1 | B0 (PSA) |
|---|---:|---:|---:|---:|---:|---:|
| 2020-01..2021-12 | 40,513 | 619 / 3 | 0.0789 | **0.0775** | 0.0786 | 0.0880 |
| 2022-01..2023-12 | 42,737 | 84 / 10 | 0.0191 | **0.0156** | 0.0163 | 0.0172 |
| 2024-01..2026-06 | 65,539 | 157 / 11 | 0.0213 | **0.0167** | 0.0190 | 0.0199 |

Flags (pre-declared): `beats_baselines` false on every window. `log_loss_degradation` true for
2020–2021 (refinance wave). `prepay_calibration_degradation` true for 2022+. CPR-proxy MAE of the
selected model was 3.7–5.8 pp vs 1.0–2.8 pp for B2.

**Cohort run-off, 24-month cumulative payoff incidence** (Aalen–Johansen with 95% loan
bootstrap; model in hindsight-rate / as-of-flat-rate modes):

| Cohort (active at) | Loans | Realized | Selected (B1) | B2 | M1 |
|---|---:|---:|---:|---:|---:|
| 2019-12 | 1,798 | 0.333 [0.314, 0.354] | 0.317 / 0.259 | 0.350 / 0.251 | 0.328 / 0.250 |
| 2021-12 | 1,609 | 0.050 [0.040, 0.061] | 0.172 / 0.231 | 0.047 / 0.180 | 0.092 / 0.196 |
| 2023-12 | 1,991 | 0.055 [0.045, 0.063] | 0.171 / 0.161 | 0.054 / 0.035 | 0.115 / 0.113 |

What this shows:

1. The protocol reports an unflattering result as is. The selected baseline lost to B2 on
   every window, and the immutable first report records it.
2. B1's coarse incentive bins can't tell "slightly" from "deeply" out of the money, so it
   overstates payoffs in the post-2022 lock-in cohorts.
3. Hindsight vs as-of separates behavioral error from rate-path error. The 2021-12 cohort's
   as-of forecast assumed flat low rates and overpredicted refinancing that never happened.
4. LightGBM sits between the baselines: trees extrapolate poorly into incentives rarely seen in
   training.

On synthetic data, the ground-truth diagnostic (`validation.json → _truth_recovery`) agrees: B2
recovers the true hazard best (prepay MAE 0.0014 vs a mean hazard of 0.0070).

### 5.2 Larger world (`dev` preset, ~47k loans, clean)

Reproduce with `uv run prepay demo build --out build/demo --preset dev`; the evaluation is in
`build/demo/model_quality.json` (run `20261028T203803Z-39b423a7`). Same windows, same rule, same
code as §5.1.

**Selection (validation A, 164,511 rows, 548 payoffs / 27 credit):** B2 0.02308, M1 0.02331,
B0 0.02418, B1 0.02420. With more data B1's gap to B2 is significant (+0.00112, 95% loan-cluster
bootstrap [0.00093, 0.00129]), so the rule selected **B2**. Calibration was **not** adopted
(cross-fitted temperatures 1.004 and 0.990 each made the held-out fold slightly worse).

**Sealed holdout, one-step log loss:**

| Window | Rows | Payoffs / credit | Selected (B2) | B1 | M1 | B0 (PSA) |
|---|---:|---:|---:|---:|---:|---:|
| 2020-01..2021-12 | 338,854 | 5,240 / 29 | **0.0783** | 0.0793 | 0.0785 | 0.0887 |
| 2022-01..2023-12 | 356,645 | 678 / 66 | **0.0145** | 0.0174 | 0.0152 | 0.0166 |
| 2024-01..2026-06 | 546,851 | 1,407 / 114 | **0.0184** | 0.0216 | 0.0193 | 0.0211 |

Flags: `beats_baselines` true on every window. `log_loss_degradation` true for 2020–2021.
`prepay_calibration_degradation` false everywhere. CPR-proxy MAE of the selected model was
0.35–0.88 pp, vs 1.2–2.1 pp for M1 and 2.9–4.7 pp for B1. LightGBM was significantly worse than
B2 on every window (paired difference CIs all above zero) and significantly better than B1.

**Cohort run-off, 24-month cumulative payoff incidence** (hindsight / as-of-flat):

| Cohort (active at) | Loans | Realized | Selected (B2) | B1 | M1 |
|---|---:|---:|---:|---:|---:|
| 2019-12 | 15,100 | 0.338 [0.331, 0.345] | 0.338 / 0.240 | 0.321 / 0.260 | 0.353 / 0.252 |
| 2021-12 | 13,479 | 0.047 [0.043, 0.050] | 0.045 / 0.161 | 0.153 / 0.220 | 0.087 / 0.190 |
| 2023-12 | 16,608 | 0.054 [0.051, 0.057] | 0.054 / 0.035 | 0.156 / 0.144 | 0.101 / 0.084 |

Truth recovery (prepay MAE, true mean hazard 0.0071): B2 0.00056, M1 0.00161, B1 0.00279,
B0 0.00386.

**Read this with one caveat.** The synthetic truth (`src/prepay/synthetic/truth.py`) is a
multinomial logit built from smooth S-curve, seasoning and burnout terms. B2 is a spline
multinomial logit, so it is close to correctly specified here, and its win is expected. That
shows the pipeline can recover a known hazard. It says nothing about whether B2 or LightGBM
would win on real loans, where the true shape is unknown.

The two worlds also show why the selection rule matters. On ~6k loans the rule couldn't
distinguish B1 from B2 and kept the simpler model, which then lost. With 8× the data the same
rule had the evidence to pick B2. The rule wasn't changed between the runs.

## 6. Financial outcomes and sensitivity

The finance engine is verified separately (`make test-finance`, 95% coverage, 8/8 mutation
kills, `docs/validation/FINANCE_ENGINE.md`). Scenario projections report cash WAL,
exposure-exit WAL, 12/24-month returned principal, accrued contractual interest and an
out-of-support share per month. Recovery severity and lag are illustrative inputs, not
calibrated losses.

## 7. Software tests and controls

296 automated tests (2026-10-29): Decimal oracle, Hypothesis properties, mutation kills, independent label
oracle, feature parity, truth recovery, holdout spy, seal tamper detection, and one-shot lockbox
refusal. CI runs synthetic-only with SHA-pinned actions.

## 8. Limitations and open items

- The real-data study (training, one sealed opening, segments, credit sufficiency, cohort
  run-off, censoring bounds) was run privately. It is unpublished and has not been independently
  reviewed. PSI drift monitoring is **not built**.
- The real test windows (2020-01 to 2026-06) have now been opened once. Any revised model can be
  judged fairly only on reporting months after 2026-06, from a later release (ADR 0007, ADR 0008).
- Seed-repeat stability and feature ablations are not built.
- The parsimony rule is underpowered on small validation windows (ADR 0004).
- Curtailments aren't modeled; CPR figures are full-payoff-only proxies.

## 9. Change control and monitoring

Every run records its data-lock, feature-contract, software-lock and Git digests. A changed
model is a new run with its own seal, and the first holdout report of a sealed run is never
replaced. Planned monitoring: feature PSI (> 0.25 = review trigger), missingness, and observed
vs predicted payoff rates once outcomes mature.
