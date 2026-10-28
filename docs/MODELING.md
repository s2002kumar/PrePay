# Prepay | Research design, event taxonomy and validation

Version 2.0 • 2026-10-27 • Locked methodology intended *before* empirical research. Actual measurements TBD.

## 1. Prediction question and competing-risk definition

For an eligible unmodified, fully amortizing Freddie Mac Standard sample fixed-rate loan **active at the end of month t-1**, estimate month-t probabilities:

- **P**: full *voluntary early payoff* recorded as `zero_balance_code 01` with exit sufficiently before contractual maturity.
- **C**: observable terminal **credit-related disposition** recorded as codes `02` (third-party sale), `03` (short sale/charge-off) or `09` (REO disposition).
- **A**: no event, remains active at the end of month t.

`pP+pC+pA=1`. The C outcome is **not** synonymous with 90+ day delinquency, default at 90 days, final net loss or whole-loan sale. A loan's `15` status is a **whole loan sale**, not an observed credit liquidation event, and its post-sale data are unavailable. Freddie Mac's July 2026 source guide governs code meaning: https://www.freddiemac.com/fmac-resources/research/pdf/general_user_guide_july_2026.pdf.

Interpretation: competing terminal observed dispositions for the *eligible unmodified population*. Not a full credit-transition model. If terminal credit events are too sparse or censoring makes projections misleading, **prepay-only** becomes the primary model and credit dispositions are sensitivity-only, with a clear baseline assumption; no synthetic credit-performance claim.

## 2. First-event decision table (apply chronologically)

| Observed row/condition | Action | Reason |
|---|---|---|
| Start of risk | Valid prior month t-1 ending UPB >0, first payment reached, not previously terminal/censored | only truly at-risk loan-months |
| Terminal `01` sufficiently before scheduled maturity | **P** | full payoff / voluntary exit |
| Terminal `01` at/near maturity | **maturity**, not P; contract handles normal maturity | Freddie combines payoff and maturity in 01 |
| Terminal `02`, `03`, `09` | **C** | observed terminal credit disposition |
| `15` | **right censor** | whole-loan sale does not mean default |
| `16` | **right censor** | reperforming loan securitization exit |
| `96` | **right censor** | defect/repurchase category |
| First `modification_flag=Y`, without earlier definite terminal event | **right censor on modification** | modified loan does not mechanically lose principal; original contract changes |
| Loan already flagged prior modification `P` at first observation | exclude at entry, record | not eligible original-contract history |
| 90+ days delinquent, disaster Y, plan F/R/T, `RA`, `XX` | remain observable state, not event by itself | financially not equal to realized liquidation |
| Unexpected codes, same-month modification+terminal, missing effective dates, gaps | quarantine pending documented precedence policy + source tests | never silently guess |
| No next month at release cutoff | administrative right censor at cutoff | no subsequent outcome observable |

For ambiguity around maturity, implement initial `01` within **two months** of contractual maturity as maturity, with separate one-month/zero-month sensitivity; confirm on validation distributions. Use actual `zero_balance_effective_date` only in accordance with official chronology; reconcile last reporting month to effective month. The terminal event is dated when known in the file, not back-propagated using future records to features. Document if ending UPB has rounding behavior for first six months or deferred components; do not use post-event UPB as a feature.

**Key bias:** Modifications, sales and disaster interventions are informative censoring, not necessarily random. State this and quantify by vintage and time; do not pretend simple observed cohort runoff is an unconditional population forecast. Distinguish modeled loan attrition from full original-pool disappearance.

## 3. Data source contract

- Freddie Mac Single-Family Loan-Level Dataset **Standard sample**; July 2026 Release 47 current guide includes sample 50,000 per complete vintage and partial-year proportional sample. As of Oct 2026 public dataset page states performance disclosed through **March 31, 2026**, but actual downloaded package metadata is authoritative.
- Raw `sample_YYYY.zip`, origination `sample_orig_YYYY.txt`, performance `sample_perf_YYYY.txt` are headerless, pipe-delimited. Confirm **exact release file-layout column positions** before implementing parser; track schema version and release fingerprints.
- FRED PMMS `MORTGAGE30US`, `MORTGAGE15US`: weekly series, construct monthly rates by explicitly documented sample observation dates. November 17, 2022 is a data-generation method transition; document discontinuity/sensitivity instead of falsely inferring a change in borrower behavior.
- A sample drawn from a fixed vintage by Freddie does not necessarily replicate full-portfolio weighted mixes. Do not extrapolate results to all US loans or true MBS securities.

## 4. One-step features and future-path completeness

Allowed static: original coupon/note interest, original 15/20/30 year term bucket, origination FICO/LTV/CLTV/DTI/MI %, original UPB and original purpose, occupancy, units, first-time buyer, acquisition channel, state region and borrower count encoded in a consistent historical schema. Normalize missing sentinels by field + era, do not map missing to zero.

Allowed path features as-of t-1: calendar month, original-contract seasoning/remaining term, market PMMS by matched term at t-1 and t-2, note-vs-market incentive in basis points, lagged 6-month market change, cumulative number of prior incentive months (burnout) using only information through t-1. `sato` origination spread requires the contemporaneously available PMMS date preceding first payment; if rate observation is missing, mark missing rather than use an incorrectly future observation.

Features **not** in v1: current delinquency state (not forecastable without transitions), current balance as a behavioral covariate (would require explicit projected state parity), post-modification coupon, future rates, observed outcomes t or later, current LTV (era dependent) and servicing collections. The finance engine uses current projected balance and schedule, but main behavioral model does not require actual future balance paths.

Scenario feature generator takes `(original state, historical rate prefix through t0, hypothetical rates t0+1..t0+H)` and returns an H-step feature matrix with no access to realized future borrower outcomes. Parity test on historical path matches gold at all supported dates, including first observed payment, PMMS gaps and post-2022 boundary.

## 5. Time windows and protocol

| Name | Calendar outcome months | Purpose |
|---|---|---|
| Train | earliest available through 2017-12 | fitting only |
| Validation A | 2018-01..2018-12 | model selection, early stopping |
| Validation B | 2019-01..2019-12 | calibration, assumptions, threshold choices |
| Test A | 2020-01..2021-12 | COVID/refinancing wave, untouched holdout |
| Test B | 2022-01..2023-12 | rate tightening, untouched holdout |
| Test C | 2024-01..verified cutoff | most recent cohort shift, untouched holdout |

Time-split follows prediction *target month*, not random row or loan; previously observed state of a surviving loan can legitimately inform a later prediction. The same frozen model may score all tests, without refitting. Keep 2019-May and 2025-Oct accounting transition months separately flagged; evaluate them in sensitivity rather than automatically erasing materially informative events. Do not exclude them from *all* headline windows without a transparent denominator and predeclared decision.

Train-period selection bias is meaningful: survivors seen in 2020 are not random new loans. Report performance by origination vintage, time in book and rate regime. Within train/validation, use time-aware tuning and stability repeats as available; never let outcome labels from tests select features or thresholds.

**Sealing:** Pre-register model candidates, primary model choice rule, cash-flow conventions, loss assumptions, dataset/schema and data snapshot, calibration, report definitions and allowed exclusions before testing. No dashboard preview of test actuals for experimentation. First sealed evaluation is immutable and release-reportable even if disappointing.

## 6. Models and coherent probabilities

- **B0 PSA** industry reference for prepayment hazard **only**; separately registered simple credit disposition hazard derived from train rates. No claimed three-class superiority from PSA by itself.
- **B1** pooled empirical model by loan-age and incentive bins, with smoothing and defaults for sparse groups. Three coherent probabilities.
- **B2** regularized multinomial logistic regression with splines on seasoning/incentive; train-only imputation/encoding. Strong interpretable supervised benchmark.
- **M1** gradient boosted **multiclass** LightGBM or other explicitly validated categorical implementation returning joint three-class softmax probabilities. Do **not** use two independent binary LightGBM classifiers with `pP+pC` clipped to 1: clipping invalidates risk coherence and calibration.

Because native multiclass gradient boosting may not offer convenient per-class monotonic constraints, **do not assert guaranteed monotonicity**. Test conditional sensitivity across realistic feature sweeps. A documented challenger can combine (a) a binary exit-vs-survive model and (b) a prepay-vs-credit split model, giving `pP=pExit*pPrepayGivenExit`, `pC=pExit*(1-pPrepayGivenExit)` and `pA=1-pExit`, if validation supports it. This construction is coherent but conditional model calibration/rare outcomes must be checked. Choose the candidate honestly on **validation**, not by complexity or desire for an impressive algorithm.

No random row oversampling unadjusted for prevalence. Fit class weights only if calibrated posterior corrections and validation justify them. If sampling for memory, sample **whole loan paths** with clearly tracked inclusion probabilities and preserve event/age/rate regime representation; apply consistent evaluation in untouched full holdout where computationally possible. Store full preprocessing and model with data/version hashes.

Calibration: compare raw and fitted temperature/Platt or a truly multiclass calibration method on Validation B using proper scoring rules; never fit on test. Evaluate 3-class reliability and the meaningful minority credit class independently; choose calibration only if validation improvement is stable, not on an arbitrary 1% hard rule.

## 7. Evaluation hierarchy

**Primary predictive outcomes (one-step, proper scoring):** monthly balance-weighted voluntary-payoff proxy CPR bias + MAE, **and** joint multiclass log loss + Brier score on the at-risk panel. Designate one as primary in `run-manifest` before sealing. Use a stable evaluation cohort/exposure definition across competing models; report class-conditional reliability and confidence intervals clustered by **loan**, not row.

**Secondary diagnostics:** PR-AUC of rare credit disposition, discrimination AUROC (not alone), calibration ECE/reliability bin counts, monthly voluntary and credit rates, vintage/incentive/term/region/loan-purpose segments, feature drift; concept checks on incentive, burnout, seasoning, seasonality and borrower credit at fixed other variables. Report test failure even when conceptual economic shape seems counterintuitive. No automated model repair using holdout results.

**Economic performance:** a controlled cohort snapshot at `t0` with balances then known; forecast cumulative voluntary principal by months 6/12/24 and remaining balance under a fully declared rate path. Compare *hindsight-rate diagnostic* against realized eligible histories with **explicit administrative and informative censor handling**; calculate raw observed and censor-adjusted event-incidence curves (Aalen-Johansen or properly justified alternative). If IPCW is used, provide censor model and stability checks; without defensible adjustment, restrict conclusions to observed risk sets and mark runoff estimand limited. Report uncertainty via loan-level/vintage-block bootstrap, recognizing time-dependence. The model must **not** condition its forward projections on which specific loans will be censored in the future.

Cash-flow validation vs true historical collections is **not available** from contractual loan balance alone for modified/delinquent loans. Compare observed exit/coupon/proxy monthly changes with assumptions and show aggregation error + residual explicitly; don't label a simulated portfolio schedule as observed MBS cashflow ground truth.

For each rate shock, report weighted-average life, 12/24m returned-principal %, contracted interest accrued, scenario-to-base differences in **months / percentage points / dollars**, plus out-of-support diagnostic. Scenario behavior is a sensitivity, not a calibrated probability of future rate decisions.

## 8. Financial backtests and uncertainty

- Always score monthly one-step events with known t-1 features; separately run 12/24-month rollforward **without using realized loan event rows for later feature updates**.
- Evaluate loan-level engine against rep-line approximation on synthetic and private validation cohorts. Rep lines are *private approximations* not authorized public outputs.
- Fixed severity and lag assumptions do **not** equal learned or accurately realized losses; material outcome sensitivity must be charted.
- Report evaluation using actual historic PMMS paths as a **hindsight diagnostic** only; do an explicit as-of rate-path scenario study and show the different error attribution.
- Compare proper coverage/intervals for bootstrap or simulation uncertainty; don't call scenario bands confidence intervals unless justified.

## 9. Go/no-go criteria (chosen before test)

**Required engineering gates:** source authenticity + schema validity; leakage tests; probability simplex; lineage; reproducibility; financial conservation; honest two-baseline comparison; publication boundary. Missing any one means no full release.

**Performance policy:** The GBM must be *benchmarked* against B1 and B2 on every holdout. Selection based on Validation A/B. A model beating both baselines is a nice result, **not a guaranteed condition and never a reason to retune the sealed holdout**. If none beat the simple baseline or test calibration degrades materially, use stronger simple baseline and prominently document ML failure and regime shift. Publish actual scores only after lawful data access and evaluation.

**Concept sanity:** economic stress/incentive tests should be informative, but global monotonic constraints for all observed behavioral patterns are not legally or mathematically guaranteed. Report counterexamples; investigate for leakage/bugs and discuss genuine regime limitations.

## 10. Monitoring / model-risk handoff

Validation report: intended use, source/coverage/consent, quality/provenance, competing exits/censors, methodology, fit/calibration, segments/uncertainty, financially relevant outcomes, sensitivity, concept tests, software tests, limitations, change control and monitoring. Use OSFI E-23 May 2027 framework and US interagency SR 26-2 (Apr 2026) as **design inspiration only**, not certification or regulatory compliance.

Drift: PSI + missingness, population selection changes and true observed performance when labels mature; PSI >0.25 is a *review trigger*, not automatic causal evidence. Keep release registry and rollback-to-baseline ability. No claims of independent validation by a human reviewer unless that actually occurred.

## 11. Historical facts requiring explicit caveats

- Freddie release is corrected over time; cohort results are tied to the download release fingerprint.
- 2020 forbearance can obscure interpretation of early credit events.
- `01` combines prepaid and matured; approximating split by contractual maturity is not observed perfect truth.
- 90+ delinquency may cure and is not terminal. Most credit losses materialize later than delinquency.
- PMMS November 2022 method shift is not automatically an economic break.
- Missing actual curtailments can bias full-payoff-only SMM proxy vs official industry CPR.
- Dataset not suitable for directly mapping Freddie-backed securities / making trading decisions under its terms.

## 12. Version log

| Date | Version | Reason |
|---|---|---|
| 2026-10-27 | 2.0 | corrected event codes/modification labels, coherent ML, cashflow/actual separation, honest holdout, licensing boundary |
