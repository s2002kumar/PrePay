# Financial ML reliability improvement program

- Status: **active**. Started 2026-10-29, after the single real-data lockbox opening (ADR 0006).
- Protocol: [ADR 0009](decisions/0009-reliability-program-protocol.md) (evidence classes,
  rolling-origin development, private execution).
- Prospective test: [ADR 0008](decisions/0008-forward-experiment.md) and
  [ADR 0010](decisions/0010-forward-evaluation-preregistration.md).
- Readers: the owner, model-risk reviewers, and engineers continuing the work.

Prepay is **not approved** as a reliable financial forecasting product. This program tries to find
out why the frozen model failed across rate regimes. It builds better-justified alternatives and
safeguards. It then tests them on outcomes nobody has seen yet. Its goal is the strongest
defensible forecaster for this data and scope, not a LightGBM win. Where the system stays
unreliable, it has to say so.

## 1. What is frozen

These stay unchanged: the sealed primary run, its data lock, seal, `evaluations/first.json`, the
ADR 0004 selection and calibration decisions, and the private review packet. No experiment
re-scores the opened 2020-01 to 2026-06 windows in order to revise a claim about them.

## 2. What failed

The owner's program brief states the failures without figures. The figures stay in the private
packet (ADR 0006 §3).

1. The selected model, LightGBM with temperature scaling (M1+T), **overpredicted voluntary
   payoffs** in the recent higher-rate environment.
2. It **underpredicted the 2020–2021 refinance wave**.
3. The **credit-disposition hazard was poorly calibrated**.
4. The failures **differ by rate regime**. Whether calibration itself shifts between regimes is
   still open (H-CAL).

## 3. Audit findings

These are findings from the code and from public PMMS data. They are facts about the
implementation and the rate history, not about real loan outcomes.

### 3.1 Public rate history

FRED PMMS 30-year, month-end as-of. Each target month t uses the rate known at the end of t−1, as
the models do. Reproduce with §11.

| Fact | Value |
|---|---|
| Training window (target months 1999-01..2017-12) 30y rate range | 3.32%–8.62% |
| Training months with the 30y rate above 5.5% | 117, **all before 2009** |
| Test A (2020-01..2021-12) months below the training minimum | **20 of 24** (low 2.67%) |
| Test B (2022-01..2023-12) months above 5.5% | 17 of 24 |
| Test C (2024-01..2026-06) months above 5.5% | **30 of 30** |
| Largest 6-month rise in training / in 2022–23 | +111 bp / **+259 bp** |
| Largest 6-month fall in training / in 2020–21 | −168 bp / −61 bp |
| New-low months (rate below its trailing 60-month low): training / Test A | 28 / 9 |

So in training, "the 30-year rate is above 5.5%" means "this is 1999–2008" without exception.
The refinance wave ran mostly at rate levels never seen in training. The 2022 rate shock was more than
twice the largest training-era rise.

### 3.2 Implementation findings

| ID | Finding | Where |
|---|---|---|
| A1 | Absolute rate levels `market_rate_t1` and `note_rate_pct` are model inputs. B2 uses them linearly, M1 in trees. | `features/spec.py`, `modeling/design.py` |
| A2 | Nominal loan size (`log_original_upb`) drifts upward with house prices and inflation, so it also tracks era. | `features/spec.py` |
| A3 | Trees extrapolate as constants beyond the training range. B2's spline terms are clipped at the training min and max, so B2 extrapolates only through its linear terms. | `modeling/models.py`, `modeling/design.py` |
| A4 | The scenario out-of-support flag is univariate (3 features, 0.5–99.5% quantiles). It ignores joint support and event counts, and nothing in the forecast changes when it fires. | `scenarios/projection.py` |
| A5 | Selection (2018) and calibration (2019) each use one year from one regime. Nothing measures whether calibration transfers between regimes. | `modeling/train.py` |
| A6 | The training sample is one fixed 10% loan subset defined by DuckDB `hash()`. Its sampling variance is unmeasured. The hash isn't documented as stable across DuckDB versions, so the subset is reproducible only under the pinned lock. | `features/panel.py` |
| A7 | LightGBM uses one fixed seed. Seed-repeat stability isn't measured. | `modeling/models.py` |
| A8 | Burnout counts months with incentive above 50 bp since first payment. It never decays and ignores how deep in the money the loan was. | ADR 0003 §6 |
| A9 | One global temperature for all three classes, fitted on 2019 only. | `modeling/train.py` |
| A10 | The credit hazard feeds projections as a forecast, although ADR 0006 §8 treats it as an assumption unless validated. | `scenarios/projection.py` |
| A11 | The run-off "curtailment" residual re-amortizes each loan's observed balance every month (a recast convention). US fixed-rate loans normally keep their payment after a curtailment. For loans that curtailed earlier, the residual then mislabels part of scheduled principal as curtailment. | `evaluation/runoff.py` |
| A12 | Run manifests record the Git SHA but not whether the working tree was dirty. | `provenance.py` |
| A13 | Hindsight and as-of modes both exist in the cohort backtest, but the error isn't decomposed explicitly into behavior and rate path. | `evaluation/cohort.py` |

## 4. Ranked failure hypotheses

The ranking combines how strongly the public evidence and the code point at a hypothesis, how much
of both failures it could explain, and whether it can be tested before the forward evaluation.
**Supported** means public evidence or a mechanism shown on synthetic data. It doesn't mean the
hypothesis is confirmed on real loans.

| Rank | ID | Hypothesis | Explains | Evidence now | Test (§6) | Falsified if |
|---:|---|---|---|---|---|---|
| 1 | H-SUP | **Out-of-support extrapolation.** Deep negative incentives, sub-3.3% rates and >+111 bp rate shocks never occur in training. Trees hold the edge value, so lock-in turnover is too high and the low-rate refi response is capped. | 1, 2 | Supported: §3.1 public facts; synthetic mechanism (ADR 0007) | D2, D3, M-R, P1 | Refits through 2026-06 don't beat the ≤2017 runs on forward months, *and* forward rows are mostly in support |
| 2 | H-ERA | **Absolute rate level and nominal loan size act as era proxies.** Every >5.5% training month is 1999–2008, an era of fast housing turnover and cash-out refinancing. A model that learns "high rate ⇒ fast payoffs" applies that era to 2022+. | 1 (and partly 2) | Supported: §3.1; A1, A2 | D1, D2 (level at fixed incentive), M-X1/X2, V1 | Removing level features doesn't reduce the level response on development folds *or* the forward overprediction |
| 3 | H-BURN | **Burnout is misspecified.** A count that never decays treats loans in the money in 2012–2016 as burned out, but the deeper 2020 incentive brought them back. | 2 | Hypothesis: A8 | D2 burnout probe, M-X3/H1 "new-opportunity" feature, V1 2012 fold | The new-opportunity term adds nothing in development folds that contain a new-low wave |
| 4 | H-CAL | **Calibration is regime-dependent.** A 2019 temperature doesn't transfer to refi waves or lock-in. | 1, 2, 4 | Hypothesis: A5, A9 | D4 on V1 folds | Fold-level A/E stays within [0.9, 1.1] across regimes after calibration |
| 5 | H-MISS | **Missing economic state:** home equity (HPA), housing turnover and refinance capacity or credit availability. 2009–2012 refinancing was held back by negative equity and tight credit; 2020–2021 was boosted by equity gains and streamlined refinancing. | 1, 2 | Hypothesis. MODELING §4 excludes current LTV, and new external data needs an owner decision. | Owner decision O3 | A model with equity proxies doesn't improve forward or development folds |
| 6 | H-MEDIA | **New-low (media) effect missing.** Refinancing surges when rates hit multi-year lows, beyond the bp incentive alone. | 2 | Hypothesis; training contains new lows (2002–03, 2008–12) | M-X3/H1 new-low feature, V1 | No development gain in new-low folds |
| 7 | H-RATE | **Unknown rate paths** dominate as-of forecast error: 2020 rates kept falling, 2022 rates rose ~300 bp. This is forecast error, not behavioral error. | forecast error | Mechanism in synthetic (VALIDATION_REPORT §5) | D5 decomposition | Hindsight error ≈ as-of error |
| 8 | H-SAMP | **Training sample instability:** one fixed 10% subset could make the model or the selection depend on which loans were drawn. | all, 2nd order | Unmeasured (A6) | D6 | Across 5 disjoint samples, validation log loss and response curves vary well inside the between-model gaps |
| 9 | H-COMP | **Survivor composition:** the post-2020 at-risk book is dominated by very low-coupon 2020–21 vintages, unlike any training cohort. | 1 | Overlaps H-SUP | D3 by vintage | — |
| 10 | H-REP | **Reporting changes:** cycle changes in 2019-05 and 2025-10, and UPB rounding in the first 6 months. | timing | Documented source facts | F1, flagged months | Flagged months don't differ from neighbours |
| 11 | H-CENS | **Informative censoring:** forbearance, modifications and loan sales during 2020–21. | cohort metrics | Bounds exist (ADR 0006 §10) | D5 bounds | Bounds narrow relative to model errors |
| 12 | H-CREDIT | **Credit dispositions depend on the era** (crisis 2008–12 vs forbearance and moratoria 2020–21), and features cannot see policy. | 3 | Supported by design; A10 | F2 | — |

H-SUP and H-ERA predict different things. Under H-ERA, a model *without* level features improves
even when trained only through 2017 (X1/X2 vs M1). Under H-SUP, a model *trained through 2026*
improves even with level features kept (R-arm). ADR 0010 registers both arms so the forward
months can tell them apart.

## 5. Evidence classes (ADR 0009 §2)

| Class | Data | What it can support | Label in every report |
|---|---|---|---|
| E0 | Synthetic | That the software and diagnostics work. Nothing about real accuracy. | `synthetic` |
| E1 | Real, outcome months ≤ 2019-12, rolling-origin | Development evidence for ranking and diagnosing candidates. These candidates were designed after the 2020–26 failures were seen, so E1 can't confirm them. | `development` |
| E2 | Real, opened 2020-01..2026-06 | Exploratory post-mortem only. Never a claim of improvement on those months. | `exploratory-opened-window` |
| E3 | Real, reporting months after 2026-06 from a later release | The only class that can confirm an improvement (ADR 0010) | `forward-confirmatory` |

## 6. Experiments and acceptance criteria

**Status:** `built` = implemented and tested on synthetic data · `owner-run` = needs the owner to
run it locally on real data · `blocked` = waits for data or a decision.

### Diagnostics (no model changes)

| ID | Question | Method | Acceptance / reading rule | Data |
|---|---|---|---|---|
| D1 | Which features encode era? | Per feature: how well it separates training eras (pre-2009 vs later), and PSI of each later window vs training. Feature values only, no outcomes. | A feature with era AUC ≥ 0.8 or window PSI > 0.25 is flagged era-confounded and listed in the packet | E0, E1 (feature-only) |
| D2 | Do models respond to the economics or to era? | Partial-dependence and ICE probes on Validation B rows: incentive, **rate level at fixed incentive** (note and market both shifted ±300 bp), burnout, age, seasonality, 6m rate change, nominal loan size (+50%). Each reports the training support of the probed range. | Flag a model when: payoff ICE falls with incentive in >1% of rows; mean payoff hazard *rises* with rate level at fixed incentive by >10% relative over +200 bp; or the curve is flat beyond the support edge while the economic prior says it should fall | E0, E1 |
| D3 | How much of each window is out of support? | Univariate 0.5–99.5% bounds plus joint (incentive × rate level, incentive × age, incentive × 6m change) cells with training rows and payoffs. Share of rows and balance outside or sparse. | Reported per window. Feeds R1 thresholds | E0, E1 (feature-only) |
| D4 | Does calibration transfer across regimes? | V1 folds: payoff A/E and ECE by public-PMMS regime (rate level band × 6m change direction × new-low), raw and temperature-scaled | Calibration counts as transferable if every regime cell with ≥ 50 payoffs has its A/E interval inside [0.8, 1.25] | E0, E1 |
| D5 | Behavior vs rate path | Cohort incidence and pool factor at 6/12/24 m. as-of error = behavioral error (hindsight − realized) + rate-path error (as-of − hindsight) | Reported, with censoring bounds. A model is called behaviorally wrong only when the hindsight error exceeds the censoring bounds | E0, E1, E2 |
| D6 | Sampling stability | 5 disjoint 10% loan samples (hash-bucket ranges) for every family | Stable if the SD of validation log loss across samples is under ¼ of the smallest between-family gap, and the incentive response SD is under 10% of its mean | E0, E1 |
| D7 | Seed stability | 5 LightGBM seeds per tree candidate | Same rule as D6 | E0, E1 |
| D8 | Post-mortem | D2/D3/D5 and the candidates on the opened windows | Exploratory only, banner-labeled. Never feeds a selection rule | E2 |

### Candidate models (all coherent, point-in-time safe, JSON or LightGBM-text artifacts)

| ID | Model | Economic purpose | Registered in |
|---|---|---|---|
| Ref | Sealed primary run: M1+T (selected), B1, B2, B0 | The baseline to beat | ADR 0004 |
| X1 | Factored LightGBM: credit hazard `c(x)` unconstrained; payoff hazard `h(x)` on non-credit rows, non-decreasing in incentive; no `market_rate_t1` / `note_rate_pct` | Remove the level-as-era channel (H-ERA) | ADR 0008 |
| X2 | X1, plus payoff non-increasing in burnout | Rule out reversed burnout | ADR 0008 |
| X3 | X2, plus behavioral features: rate gap to the lowest rate seen since origination ("new opportunity"), gap to the trailing 60-month low ("new low"), and payment saving in % (a level-aware incentive with an economic meaning) | H-BURN, H-MEDIA, and a defensible replacement for raw level | ADR 0010 |
| H1 | **Constrained hazard model:** logistic payoff hazard with monotone piecewise-linear incentive (non-decreasing; logit-linear tails, so lock-in keeps deepening beyond support instead of going flat), non-increasing burnout, seasoning, seasonality and borrower terms; no level features; separate logistic credit hazard; combined as in X1 | The simplest economically constrained model. Readable coefficients. Controlled extrapolation | ADR 0010 |
| R-* | B2, X2 and H1 **refit through 2026-06** (tune 2024-07..2025-06, calibrate 2025-07..2026-06) | Tests H-SUP: whether training on the current regime matters more than the method | ADR 0010 |

Acceptance for **registering** a candidate (development gate, ADR 0009 §6):
1. Coherent simplex on every scored row.
2. Point-in-time parity of every input, historical vs scenario.
3. Reproducible artifacts with a complete manifest.
4. Every D2 flag reported, never hidden.

Development results (E1) rank and explain candidates. They don't decide the product model.

Acceptance for **promoting** a model to the product (only after E3, ADR 0010 §5):
- the pre-registered primary comparison on forward months;
- the business tolerances T1–T5 met in hindsight mode;
- no D2 economic flag left unexplained.

If no candidate qualifies, the product keeps reporting *unreliable in this regime*.

### Development protocol

| ID | Design |
|---|---|
| V1 | Rolling origins o ∈ {2007-12, 2009-12, 2011-12, 2013-12, 2015-12, 2017-12}. Train on outcomes ≤ o−24, tune on o−23..o−12, calibrate on o−11..o, evaluate o+1..min(o+24, 2019-12). Same training fraction as the primary run, all candidates and baselines. Metrics: log loss, Brier, paired loan-cluster differences vs B2 and M1, CPR-proxy bias, regime calibration (D4), cohort run-off at t0 = o in both rate modes (D5). Reported per fold, plus worst fold and fold wins. |

The folds hold their own regime shifts: the 2008–09 crisis, the 2010–12 refi waves under tight
credit, the 2012 record lows (below every earlier rate, an analogue of 2020), the 2013 taper
tantrum, and the 2018 rise.

### Finance engine

| ID | Question | Method | Acceptance |
|---|---|---|---|
| F1 | Can partial prepayments (curtailments) be measured from the source? | Estimator using the original level payment (no recast) and installments paid (DDLPI advance). It excludes months with disclosure rounding (age ≤ 6), delinquency changes, deferrals, modifications and reporting-cycle transitions, and applies a dead band at the rounding resolution. Validated on synthetic paths with known curtailments, including rounding, delinquency, pay-ahead and recast/no-recast cases. | Defensible only if, on synthetic data, recall ≥ 0.9 and precision ≥ 0.95 for curtailments ≥ $500 in eligible months, **and**, privately on real data, eligible months with a one-installment DDLPI advance show a residual within ±$1 of zero in ≥ 90% of non-curtailment months. Until then curtailments stay out of the engine and are labeled. |
| F2 | Credit exits as an explicit assumption | Coherent overlay: `p_C = d(age)` from a stated CDR curve; payoff and active rescaled by `(1−d)/(1−p_C,model)` | Simplex preserved (tested); every response labels credit as an assumption unless credit is validated |
| F3 | Keep the ledger honest | Existing Decimal oracle, conservation, mutation tests; add the component report: scheduled / full payoff / partial (unmodeled) / credit exit / recoveries / contractual interest accrued vs cash | All §6 items still pass |

### Reliability safeguards

| ID | Safeguard | Acceptance |
|---|---|---|
| R1 | **Applicability monitor.** Per-row support status (supported / sparse / outside) from univariate and joint training support, PSI per feature, and a pre-declared verdict: `supported`, `extrapolating` or `unsupported`. | Thresholds fixed in ADR 0009 before any real-data run. The verdict appears in every projection and evaluation |
| R2 | **Conditional ranges.** A projection under `extrapolating` or `unsupported` reports the spread across all fitted families, plus a payoff-hazard band from the development A/E dispersion. These are labeled "model and calibration spread, not a confidence interval". | Ranges are produced from the same coherent ledger and conserve money in every member |
| R3 | **No silent substitution.** The model in use is always named. A fallback is never swapped in without a label. Under `unsupported`, the headline is the range, not a point. | API and UI tests |

### Prospective evaluation (ADR 0010)

| ID | Item | Status |
|---|---|---|
| P1 | `prepay forward register` / `prepay forward evaluate`. Register sealed runs and criteria before any forward month exists. Evaluate only months after 2026-06 from a later lock. Write once per lock; the first report with ≥ 12 forward months is the primary opening. Tests: holdout spy, tamper refusal, second-evaluation refusal. | built (synthetic) |
| P2 | Criteria: paired log loss (Holm-adjusted across the primary family) and business tolerances T1–T5 in hindsight mode. | pre-registered in ADR 0010 |

## 7. Expected implementation changes

| Area | Change | Touches the frozen run? |
|---|---|---|
| `modeling/challengers.py` | `FactoredGbm` (X1–X3), `ConstrainedHazard` (H1), monotonicity report | No; new families |
| `features/derived.py` | New-opportunity, new-low and payment-saving features from statics and the rate path. Parity holds by construction: one function for both history and scenarios. | No; opt-in |
| `modeling/experiment.py` | Experiment runs with arbitrary windows (rolling origins, refits), per-model calibration decisions, immutable manifests (dirty-tree flag, DuckDB version, sample definition, evidence class) | No |
| `modeling/diagnostics.py` | Probes D1–D3, regime calibration D4, stability D6/D7 | No; reads ≤ 2019-12 unless E2 is explicit |
| `evaluation/attribution.py` | Behavior vs rate-path decomposition (D5) | No |
| `evaluation/forward.py` | Forward registry and evaluator (P1) | No; reads the run only |
| `reliability/` | Support profile, PSI, verdict (R1); ranges (R2); credit overlay (F2) | No |
| `evaluation/curtailment.py` | F1 estimator and validation | No |
| API / web | Reliability verdict, credit-assumption label, range display | Synthetic demo only |

No new frameworks, services or neural models. LightGBM, scikit-learn, SciPy, NumPy and DuckDB
already cover all of it.

## 8. Statistical limitations

- **Contaminated development evidence.** Every new idea here was designed after the 2020–26
  failures were seen. E1 and E2 can rank and explain. Only E3 can confirm.
- **Few regimes.** The real history holds a handful of rate regimes. Rolling-origin folds overlap
  and are serially dependent, so "fold wins" are not independent trials. No p-value is computed
  across folds.
- **Forward power.** Twelve forward months come from one regime (2026–27, if rates stay high).
  A forward win shows the model works in *that* regime, not across all regimes. Monitoring
  continues with every release.
- **Loan-clustered bootstrap** ignores cross-loan dependence within a month (common rate shocks),
  so intervals are too narrow for pool-level quantities. Pool-level metrics are therefore reported
  with month-block bootstrap intervals as well.
- **Informative censoring** (modifications, forbearance, sales) biases observed incidence. Results
  inside the censoring bounds are not interpretable as model error.
- **Sampling.** Models are fitted on a 10% loan sample for memory reasons. D6 measures the
  variance this causes but can't remove it.
- **Missing variables.** Equity, housing turnover and refinance capacity are unobserved under the
  current feature contract. No model in this program can learn them.
- **Synthetic evidence** proves only that the software works. The synthetic truth is a
  multinomial logit with no era effect, so it can't reward or punish H-ERA fixes.

## 9. Reliability safeguards: design intent

A forecast is only as useful as the conditions it was validated in. The system will:

1. Classify every projection (`supported` / `extrapolating` / `unsupported`) from the training
   support of its own inputs.
2. When it isn't `supported`, show the range across families and calibrations first, name the
   unsupported features, and avoid precise-looking point figures.
3. Treat credit exits as a labeled assumption unless credit is validated (ADR 0006 §8).
4. Never swap models silently. Monitoring (PSI > 0.25, A/E out of band) raises a review flag, not
   an automatic fix.

## 10. Risks and dependencies

| Risk or dependency | Effect | Mitigation or owner action |
|---|---|---|
| Data-use permission for hosted AI (owner brief 2026-10-29) | The agent can't read real-data outputs, so every real-data experiment is owner-run | Experiments emit aggregate JSON to private paths; the runbook gives exact commands (O1) |
| Later Freddie Mac releases | E3 can't start before ~12 months after 2026-06 (around Release 52) | Mechanism and pre-registration done now; quarterly releases add monitoring reports |
| New external data (HPI, home sales) for H-MISS | Changes the locked feature contract (MODELING §4) | Proposed only; owner decision O3 |
| Memory on a 15.4 GB host | H1 and X runs at a 10% fraction | Same memory rule as ADR 0006 §5; peak RSS recorded |
| Multiplicity across candidates | False forward wins | Small primary family with Holm adjustment; everything else secondary (ADR 0010) |
| Regime in the forward window is high-rate only | A forward win doesn't show refi-wave accuracy | Stated in every forward report; the verdict is regime-conditional |
| Agent self-review | No independent validation | Reviewer packet; owner to invite a reviewer (O4) |

## 11. Reproduce the public facts

```bash
uv run prepay rates fetch --out scratch/pmms
uv run prepay diagnose rate-regimes --pmms-dir scratch/pmms --out scratch/rate-regimes.json
```

## 12. Owner actions

| ID | Action | Unblocks |
|---|---|---|
| O1 | Run the private experiment commands locally as each one is added to `docs/RESEARCH_RUNBOOK.md` §8. Results stay private. | E1, E2 evidence |
| O2 | When a release with a cutoff ≥ 2027-06 is available, lock it and run `prepay forward evaluate` once | E3 |
| O3 | Decide whether external equity or housing data (FHFA HPI, ELTV) may enter the feature contract | H-MISS |
| O4 | Invite an independent reviewer for the reliability packet | Independent validation |
| O5 | Complete the data-use permission review (hosted AI, publication) | Agent-assisted analysis of private aggregates |

## 13. Progress (2026-10-29)

| Area | Built and tested on synthetic data | Waiting for |
|---|---|---|
| Diagnostics D1–D7 | D1, D2, D3, D4, D5, D6, D7 | Owner-run E1 (RESEARCH_RUNBOOK §8); D8 needs those results |
| Candidates | X1, X2, X3, H1; DEV2017 and REFIT2026 presets | Owner training and sealing before any post-2026-06 download |
| Development protocol V1 | rolling-origin folds | Owner run |
| Forward P1–P2 | registration, evaluation, Holm families, T1–T6 | A release with cutoff ≥ 2027-06 |
| Safeguards R1–R3 | verdict, model range, range-first headline, in the demo API and UI | Real-data A/E band for R2 (needs E1) |
| Finance F1–F3 | F1 method and synthetic rule; F2 credit assumption; F3 ledger lines | F1 real-data rule (owner-run) |

The commands, evidence and dates are in `docs/STATUS.md`. The reviewer packet is
`docs/reviews/R1.md`. This plan changes only by dated amendment.
