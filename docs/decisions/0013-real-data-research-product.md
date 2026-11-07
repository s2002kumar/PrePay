# ADR 0013: Real-data research product: audit and go/no-go proposal

- Status: **accepted with revisions** by the owner on 2026-11-07. The decision record below
  supersedes the verdicts in §0 and the plan in §12 wherever they differ. The rest stays as the
  record of the audit.
- Date: 2026-11-05 (proposal), 2026-11-07 (decision)
- Scope: whether and how the private real-data study (ADR 0006, 0009, 0010) can strengthen the
  public product. Two candidate additions: **A**, a historical model-evaluation view; **B**, a
  research mode powered by a real-trained model. ADR 0006, 0009 and 0010 stay in force. If
  accepted, this ADR amends the research freeze of ADR 0011 §4 and the "final visual milestone"
  scope of ADR 0012 for the work in §12 only. It adds no model family, dataset or experiment.
- Author: the implementing agent. Self-audit, not independent review. Under ADR 0009 §3 the
  agent read **no real-data output, metric, coefficient or distribution**. The inventory below
  comes from the repository's documents and code, the names of private runs and reports, the
  blind runner's status files (exit codes, wall time, peak memory, digests, exception class
  names), and public sources. Where a fact about real-data results is stated, it is the owner's
  own statement in the reliability brief, as recorded in `docs/RELIABILITY_PLAN.md` §2.

## Decision record (owner, 2026-11-07)

The owner reviewed the proposal and approved a revised, **research-first** direction.

| ID | Decision | Effect |
|---|---|---|
| D1 | Draft an inquiry to Freddie Mac about noncommercial publication of non-reconstructable aggregate research findings, and about restrictions on derived model outputs. Don't send it yet | Drafted in the owner's private notes, not sent. Publication stays blocked |
| D2 | GO for a historical research presentation, but only after the revised model comparison and its statistical findings exist. The static data contract and synthetic fixtures may be prepared; the public research page is not built yet | Deferred until after E01. The contract will mirror E01's report schema, so it is designed after Gate B fixes that schema |
| D3 | NO to public inference with a real-trained model, and NO to B-lite, for this milestone | Nothing trained on real data is served or published |
| D4 | GO to investigate and repair the G15 memory failure in B2's cohort scoring. Then resume the unfinished rolling-origin work and the G16 stability jobs, subject to measured resource gates and numerical-correctness gates | The repair is Gate A (`docs/reviews/PREPAY_2_GATE_A.md`). Resumption is specified as experiment E01 (ADR 0014, proposed) |
| D5 | Amend ADR 0011 and 0012 only as far as needed to authorize a separate Prepay 2.0 real-data modeling research phase. Preserve the original sealed evaluation, the registered forward study and the released B+ product | ADR 0011 amendment 1; ADR 0012 amendment 1 |

**Research objective.** The phase has three aims:
- compare the existing statistical and ML models rigorously;
- investigate the documented rate-regime failures;
- improve the payoff model where evidence supports a particular change.

The first experiment, E01, tests economic generalization. It compares B2, M1, X1–X3 and H1 on
the existing rolling-origin protocol, with B0 and B1 as references. It covers calibration,
dependence-aware uncertainty, payoff error and financial run-off.

**Immediate execution is limited to Gate A:**
- audit the failed queue;
- implement and test the bounded-memory correction;
- correct the stale G15/G16 status;
- prepare the exact E01 execution specification.

No expensive private training and no website work.

### Frontend direction (proposal for a later release; not implemented)

Keep the Scenario Lab exactly as released, and avoid a redesign (ADR 0012 amendment 1). Today
the navigation lists four peers: Portfolio, Scenario Lab, Model quality, Methodology & status.
"Model quality" shows the *synthetic-trained* demo model's synthetic holdout. A reader could take
it for real-data evidence. The proposal regroups the routes into three areas, each with a fixed
data-class label in the page header:

| Area | Pages | Header label |
|---|---|---|
| **What-if analysis** | Portfolio, Scenario Lab (unchanged) | Fictional pools · synthetic-trained model |
| **Historical evaluation** | New, only when D2 and the terms allow. It holds the sealed primary study's one opening, and E01's development comparison, each labeled with its evidence class | Freddie Mac sample · aggregate results · past months |
| **Methodology** | Methodology & status; the current Model quality page, renamed "Synthetic model check" | Documentation |

- **Links.** Existing URLs keep working, and `/model-quality` stays a valid route.
- **No crossing links.** Nothing links a what-if projection to a real-data result: the two use
  different models, and a link would suggest they are one.
- **Before D2.** The Historical evaluation area shows one short page. It states what has been
  studied privately, why nothing is published yet, and the forward test's registration date.
- **Cost.** One navigation component, one renamed page and its tests. No visual-system change.

## 0. Verdict in brief

| Addition | Verdict | Why | Needs first |
|---|---|---|---|
| **A. Historical model evaluation view** | **GO**: a static, aggregate-only research chapter built from the sealed primary study, published after the owner's terms decision | Every input already exists in the immutable first evaluation. The terms permit public noncommercial research results. It is the strongest honest statement the project can make today: a pre-registered model, opened once, that failed across rate regimes, with baselines, calibration and financial consequences shown as they are | Decisions D1 (terms) and D2 (build). No retraining |
| **B. Real-trained model serving a public research mode** | **NO-GO now** for live inference, and for publishing weights, coefficients, lookup tables or training-support profiles | No real-trained model has passed a pre-registered accuracy gate: the primary failed and the candidates can't be confirmed before the forward opening. A served model is a Derived Product made available to third parties, which the terms prohibit without a separate license agreement. Model artifacts carry data-derived statistics without the 25-loan suppression applied to every published table | Revisit after (i) a forward-confirmed model, earliest late 2027; (ii) written terms clearance; (iii) an owner-held hosting account |
| **B-lite. Precomputed projections of the sealed primary model on the four fictional pools** | **CONDITIONAL GO**, after A, as a labeled research exhibit, never as a forecast | Research results on hypothetical pools. No model is shipped and nothing runs inference. It shows how a model trained on real loans behaves on today's coupons and where it is out of support. The synthetic demo stays the default | Decisions D1 and D3 |

Also found during the audit, outside the two additions: the queued R2 rolling-origin job
(G15) stopped on 2026-11-03 with an out-of-memory error during fold 2009-12, and the stability
jobs (G16) never started (§13). That needs a decision (D4) but is not part of A or B.

## 1. What real-trained models exist

All runs live under the private root, outside cloud-synced folders. None is in the repository,
CI, the container or the site. Training fractions are whole-loan hash samples (ADR 0004 §12).

| Run | Trained on | Fraction | Models | State | Evidence class |
|---|---|---|---|---|---|
| **REF**, the sealed primary run `20261029T024652Z-678625f1` | Release 48 lock; outcomes ≤ 2017-12; tuned on 2018; calibrated on 2019 | 0.1 | B0 PSA, B1 lookup, B2 spline logistic, M1 LightGBM; **M1+T selected** by the ADR 0004 rule | Sealed; lockbox opened **once** on 2026-10-29 on Test A, B and C; `seal.json` and `evaluations/first.json` read-only, digests recorded in R2 gate G1 | Primary, pre-registered |
| **DEV2017** `20261030T092202Z-DEV2017-b06af67a` | Same windows as REF | 0.1 | X1, X2, X3 (factored LightGBM, monotone payoff hazard, no rate levels), H1 (constrained hazard); designated X2 | Sealed 2026-10-30; `experiment verify` all checks pass; registered forward member | Development (E1): designed after the 2020-26 failures were seen |
| **REFIT2026** `20261102T232225Z-REFIT2026-88a77d25` | Outcomes ≤ 2024-06; tuned 2024-07..2025-06; calibrated 2025-07..2026-06 | **0.05** (memory ladder; the 0.1 attempt ran out of host memory in B2) | R-M1, R-B2, R-X2, R-H1 | Sealed 2026-11-02; verified; registered forward member | Exploratory-opened-window (E2): trained on months the primary opened |
| Rolling-origin fold **V1-2007-12** `20261103T013552Z-V1-2007-12-d618e7d4` | Outcomes ≤ 2005-12; tune 2006; calibrate 2007; evaluate 2008-01..2009-12 | 0.1 | B1, B2, M1, X1, X2, X3, H1 | Trained **and evaluated** (its `evaluations/` directory exists) | Development (E1) |
| Rolling-origin fold **V1-2009-12** `20261103T083135Z-V1-2009-12-0b39569d` | Outcomes ≤ 2007-12; evaluate 2010-01..2011-12 | 0.1 | same seven | **Trained, not evaluated**: the evaluation ran out of memory (§13) | Development (E1) |
| Folds 2011-12, 2013-12, 2015-12, 2017-12 | | | | **Not run** | |

The **forward registration** (`prepay forward register`, 2026-11-02 23:23:51 UTC, exit 0, 5,018
bytes, digest `f38038de…b80`) binds REF, DEV2017 and REFIT2026 by seal SHA-256 and candidate
digest, with seen-through month 2026-06 and Release 48 as the only release on disk. The rehearsal
of the opening finished 2026-11-03 00:41 UTC at a 2.0 GB peak. Both are unchanged and nothing in
this proposal touches them.

There is **no other real-trained model**: no retrained primary, no late candidate, no equity
arm (blocked on O3).

## 2. What real-data performance evidence exists

Every artifact is private. "Content" is what the code writes (`src/prepay/modeling/lockbox.py`,
`evaluation/*.py`, `modeling/experiment.py`, `modeling/probes.py`); the agent has not read the
values. "Class" is the ADR 0009 §2 evidence class.

| Artifact (private root) | Content | Class | Publishable as |
|---|---|---|---|
| REF `evaluations/first.json` (read-only, digest in R2 G1) | For Test A (2020-01..2021-12), B (2022-01..2023-12), C (2024-01..2026-06), every model and the selected model: log loss with loan-cluster interval, Brier, prepay AUROC and ECE, 10-bin reliability table, credit PR-AUC and prevalence, balance-weighted `full_payoff_only_CPR_proxy` bias and MAE **with the monthly model-vs-observed series**; paired log-loss differences (selected vs the other baselines; M1 vs B1 and B2); the four pre-declared flags; credit gating; ADR 0006 §7 segment tables (vintage, age, incentive, credit score, LTV, purpose, term) with rows, loans, observed vs expected, A/E and interval, low-event and poorly-served marks, cells < 25 loans suppressed; cohort backtests at t0 = 2019-12, 2021-12, 2023-12: Aalen-Johansen realized incidence with loan-bootstrap interval at 6/12/24 months vs each model in hindsight-rate and as-of-flat-rate modes, plus ADR 0006 §10 censoring bounds and censored-loan profiles; balance run-off: observed vs model pool factor, principal components, horizon-truncated WAL | Primary | Aggregate research results (the core of Addition A) |
| REF `validation.json`, `run-manifest.json` | Validation A/B metrics per model, selection, calibration decision, credit-sufficiency decision (ADR 0006 §8), feature support bounds, digests | Primary | Selection and calibration facts; support bounds only after review (they are data quantiles) |
| `reports/real/diagnose-incentive.json` (pre-seal) | B1 bin support and each model's incentive response on Validation B | Primary diagnostics | Response curves, after review |
| `reports/real/profile.json`, `audit.json`, `warehouse-fingerprint.json` | Volumes, quality findings, missingness, chronology (outcomes through 2019-12); oracle-vs-dbt agreement counts; table hashes | Process | Counts and agreement rates |
| `reports/real/lockbox-rehearsal-validation.json` | Rehearsal on Validation B | Not evidence | No |
| `reports/real/exploratory-after-opening.json`, `exploratory-rate-level-probe.json` | Post-opening exploratory analyses from the first study | E2 | Only under the exploratory banner, and only if the owner wants them |
| `reports/real/r2/diagnostics-primary.json` (+ `.support.json`) | D1 era-encoding flags per feature; D2 probes of every REF model (incentive, rate level at fixed incentive, burnout, age, seasonality, 6-month change, loan size) with ICE monotonicity; D3 support maps of every window (feature columns only) | Development | Flags, response curves and support shares, after review; the joint-cell counts in `.support.json` stay private |
| `reports/real/r2/curtailments-development.json`, `curtailments-exploratory-opened.json` | F1 feasibility study and its pre-declared decision | Development / E2 | The decision and residual quantiles, after review |
| `reports/real/r2/verify-*.json` | Member verification booleans; fitted-model monotonicity | Engineering | The `all_pass` flag is already public |
| DEV2017 and REFIT2026 `validation.json` | Tune and calibrate metrics, monotonicity checks, feature support | E1 / E2 | Not before the forward opening (§8) |
| Fold V1-2007-12 `evaluations/` | Metrics, paired differences vs B2 and M1, regime calibration (D4), cohort and run-off backtests with D5 attribution | E1 | After G15 completes, as "development evidence" |
| Forward rehearsal report | Every registered model on 2025-07..2026-06 under the forward code path, with tolerance verdicts | Rehearsal, not evidence | No (the members had seen those months) |
| `reports/REAL_DATA_REVIEW_PACKET.md` and the private notes | The study's narrative, figures and failed checks | Private packet | Source for the owner's review, not for publication as is |

Known limits of this evidence, independent of its values: segment and lockbox intervals are
loan-cluster only and too narrow under shared monthly shocks (R2 defect 2); the run-off
"curtailment" line is a recast-convention residual that overstates curtailments for US loans
(defect 1); REF trained on a 10% loan sample and REFIT2026 on 5%; the primary manifest predates
the dirty-tree flag (defect 5); D6/D7 stability is unmeasured (§13); no independent human review
has taken place (O4).

## 3. Which windows are examined, and which are untouched

| Window | Outcome months | Role for REF | Also seen by |
|---|---|---|---|
| Train | ≤ 2017-12 | fitting | DEV2017 fitting; folds (as train, tune, calibrate or evaluate); REFIT2026 fitting |
| Validation A | 2018-01..2018-12 | selection and tuning | DEV2017 tuning; folds; REFIT2026 fitting |
| Validation B | 2019-01..2019-12 | calibration | DEV2017 calibration; the V1-2017-12 fold would evaluate here (not run); REFIT2026 fitting; D2 probe reference rows |
| Test A | 2020-01..2021-12 | **opened once, 2026-10-29** | REFIT2026 fitting; D3 (feature columns only); curtailment exploratory study (balances) |
| Test B | 2022-01..2023-12 | **opened once, 2026-10-29** | REFIT2026 fitting; D3; curtailments |
| Test C | 2024-01..2026-06 | **opened once, 2026-10-29** | REFIT2026 fitting (to 2024-06), tuning (to 2025-06) and calibration (to 2026-06); the forward rehearsal (2025-07..2026-06, all members); D3; curtailments |
| Forward | 2026-07 onward | never seen | **Not on disk.** Release 48's cutoff is 2026-06-30 and no later release has been downloaded (registration record, G13) |

**There is no genuinely untouched historical window in the data the project holds.** Every
reporting month through 2026-06 has been scored by the sealed primary lockbox, and every month
through 2026-06 was read when REFIT2026 trained. The only untouched months are future ones:
the forward evaluation needs a release with a cutoff of at least 2027-06, which is Release 52
on Freddie Mac's quarterly cadence, around late 2027 (ADR 0010 §2). Interim releases (49, 50,
51) must not be evaluated (no interim looks).

Two consequences that this proposal observes strictly:

- Test A, B and C remain a legitimate **first-and-only holdout for REF**. Its report is the
  honest result of a pre-registered study and can be presented as such, failures included.
- For DEV2017, REFIT2026 and the folds, those same months are **not** a holdout. They can only
  be shown as development or exploratory evidence under the ADR 0009 banner. No table in this
  proposal relabels them, and no candidate is scored on them to claim improvement.

## 4. What can honestly be demonstrated now

**Can be shown, from existing artifacts, without retraining or re-scoring:**

1. A pre-registered real-data study, run end to end on the Release 48 Standard sample:
   verified layout, data lock, streaming ingest, audited labels, point-in-time features,
   validation-only selection, seal, one opening.
2. The sealed model's **actual vs predicted** monthly full-payoff CPR proxy over 2020-01..2026-06
   against three baselines, with the pre-declared flags, including the failures the owner
   reported: overprediction after 2022, underprediction in 2020-21, a poorly calibrated credit
   hazard.
3. **Calibration** per window: reliability tables, overall payoff A/E, and bottom- and top-fifth
   A/E (derivable exactly from the equal-count bins).
4. **Errors by rate regime**, by joining the monthly series to the public PMMS regime bands of
   ADR 0009 §5 (level band, six-month direction, new low). This is a presentation of
   pre-registered outputs against public rates, not a new real-data computation.
5. **Financial consequences** that the data can measure: cohort payoff incidence (loans) and
   balance run-off (pool factor in pp of balance, principal components, truncated WAL in years)
   at 6/12/24 months for three cohorts, in hindsight-rate and as-of-rate modes, with censoring
   bounds; and ADR 0010's business tolerances T1-T6 applied descriptively to REF per window
   (labeled post hoc: the tolerances were pre-registered for the forward test, not for these
   windows).
6. **Where the model has support**: D3 shares of each window outside or at the edge of training
   support, and the public rate facts (every training month above 5.5% is pre-2009; 20 of 24
   Test A months lie below the training minimum).
7. The **forward test as a commitment device**: the registration's digest, time, members' seal
   hashes, comparison families and tolerances, all of which contain no data.

**Cannot be shown, and the view must say so:**

- Any claim that a candidate (X1-X3, H1, R-*) improves on the sealed model. Only the forward
  opening can show that.
- Actual cash collections, interest received, realized losses or recoveries: the source holds
  balances, not cash. Severity and lag are illustrative inputs.
- Curtailments: unmodeled; every CPR is a full-payoff-only proxy.
- Anything about Freddie Mac securities, the whole US market or trading: the sample is a sample,
  and the terms forbid mapping to securities.
- Independent validation: all reviews so far are agent self-review.

## 5. Most valuable financial metrics and visualizations (ranked)

Each item names its source field in the first evaluation, its unit and how it is derived. "No
new computation" means the published value is read from the sealed report or derived from it
with public data only. The visual system is the B+ system of ADR 0012; model-family spreads
remain hatched brackets, never confidence bands.

| # | View | Source | Unit | Why it matters |
|---|---|---|---|---|
| 1 | **Window timeline**: train, validation A/B, test A/B/C and forward, over the public PMMS 30y path with regime shading; the opening date and the forward cutoff marked | windows, public FRED | months | Makes the holdout discipline visible before any number |
| 2 | **Actual vs predicted payoff speed**, monthly, 2020-01..2026-06: observed CPR proxy, selected model, B0/B1/B2/M1 as thin lines, regime bands | `cpr_proxy.monthly` per model and window | % per year | The headline: where and how far the model was wrong |
| 3 | **Error by rate regime**: mean bias and MAE per regime cell, with a month-block bootstrap interval computed from the monthly series | item 2 joined to ADR 0009 §5 regimes | pp of CPR per year | Answers "wrong where?" with an interval that respects shared monthly shocks (unlike the loan-cluster intervals in the report) |
| 4 | **Baseline comparison table**: log loss, Brier, AUROC, CPR MAE per window and model; paired differences with intervals; the four pre-declared flags | `results[window][model]`, `_flags` | nats, pp | Shows whether ML beat simple methods, honestly (loan-cluster caveat stated) |
| 5 | **Calibration**: reliability diagram per window; overall A/E; bottom and top fifth A/E; ECE with the base-rate caveat | `prepay.reliability`, `prepay.mean_predicted`, `events`, `rows` | ratio | The 2022+ overprediction appears here as A/E well below 1 |
| 6 | **Cohort incidence curves** for the 2019-12, 2021-12 and 2023-12 cohorts: realized Aalen-Johansen with its interval and censoring bounds; model in hindsight and as-of modes; the behavior-vs-rate-path decomposition (as-of minus hindsight; hindsight minus realized) | `cohort_backtests` | share of loans | Separates "wrong about borrowers" from "didn't know the rate path" |
| 7 | **Balance run-off and consequence panel**: pool factor at 6/12/24 months observed vs model (pp of t0 balance); principal components (full payoffs, continuing amortization incl. unmodeled curtailments, credit exits); truncated WAL error (years); a "per $100 of balance" reading | `runoff_backtests` | pp, years, USD per 100 | The financial meaning of the error for a holder of the pool |
| 8 | **Tolerance scorecard**: T1-T6 for REF per window, descriptive | derived from 2, 5, 6, 7 and segments | pass/fail with values | Puts the failure in the business units the project committed to for the forward test |
| 9 | **Segment A/E heat tables**: vintage, age, incentive (deep out-of-the-money cells highlighted), credit score, LTV, purpose, term; poorly-served and low-event marks; cells under 25 loans already suppressed | `_segments.dimensions` | ratio | Shows the lock-in failure by incentive bin, the pre-registered diagnosis of ADR 0007 |
| 10 | **Support map**: share of rows and balance outside or thinly supported per window, by monitored feature | `diagnostics-primary.json` D3 | share | Explains the failure mechanism (H-SUP) without claiming a fix |
| 11 | **Credit panel**: sufficiency decision; where interpretable, credit A/E and PR-AUC; otherwise "assumption" | `credit_sufficiency`, `_credit` | counts, ratio | Honors ADR 0006 §8 |
| 12 | **Development evidence** (after G15/G16): per-fold log loss and A/E for all families, regime calibration, D1/D2 probe curves (rate level at fixed incentive) | folds, `diagnostics-primary.json` | | The research story: why rate level acts as an era proxy; labeled E1, never a win |
| 13 | **Forward test record**: registration digest and time, members, families, tolerances, status "waiting for a release with cutoff ≥ 2027-06" | registration, paths stripped | | Public commitment; zero data content |

Visualizations 2, 3, 6 and 7 are the ones that would make a model-risk reviewer or an analyst
trust the project; 8 and 13 are the ones that make the claims auditable.

## 6. Permissions: what the Freddie Mac terms allow

Source: Freddie Mac, *Terms and Conditions for Single-Family Loan-Level Dataset*, website
version effective November 2025, last updated 2025-11-03 (fetched 2026-11-05). This is a reading
by an engineer, **not legal advice**; the decision is the owner's (O5). The clauses that matter:

- **Internal Purpose.** Use is "solely for your personal, or for your company's or your
  organization's internal, purposes related to analyzing or researching credit performance of
  the mortgage assets". Derived data and "Derived Products" may be disseminated "solely within
  your own company or organization for the Internal Purpose".
- **Research exception.** "You may also use the Single-Family Loan-Level Dataset for academic or
  research purposes, and make your academic or research results and any related Derived
  Products available to the public, provided that any such distribution is solely for
  noncommercial purposes and further provided that the same does not include and cannot be
  used to derive or recreate any part of the Single-Family Loan-Level Dataset or to identify
  any specific individual".
- **Third parties.** "You are prohibited from licensing, distributing, providing, re-posting, or
  otherwise making available, with or without charge, the Single-Family Loan-Level Dataset (in
  whole or in part) or any Derived Products to any third party, except as may be required by
  applicable law. If you wish to license or distribute … Derived Products to any third party,
  you must first enter into a separate license and distribution agreement with Freddie Mac."
- **Securities.** Not for mapping to Freddie Mac MBS data or for trading and investment decisions
  relating to those securities.
- **Re-identification.** No linking to other information to identify individuals.

How that reads for each output class:

| Output | Reading | Confidence |
|---|---|---|
| Aggregate evaluation tables and curves over tens of thousands of loans, cells under 25 loans suppressed, no identifiers, published noncommercially with attribution | Research results under the research exception; cannot recreate any part of the dataset | High, subject to the owner confirming the noncommercial character of a public portfolio site |
| Monthly observed payoff rates over the whole sample; cohort counts; pool factors | Same | High |
| Precomputed projections of a real-trained model on **fictional** pools (B-lite) | Research results about model behavior; no record of the dataset is involved | Medium-high |
| D1/D2 probe curves, D3 support shares | Research results | Medium-high |
| Training-support quantiles and joint-cell counts (`feature_support`, `.support.json`) | Data-derived statistics; publishable only in coarsened form, if at all | Medium |
| **Model artifacts**: LightGBM text (split thresholds and leaf values), B2 coefficients, **B1 lookup table (empirical cell frequencies)**, preprocessor medians and knots | Derived Products. Publishing them is distribution to third parties; the research exception protects "results", and a lookup table of cell frequencies is closer to data than to a result | Low: not without a license agreement or written clearance |
| **Live inference** with a real-trained model behind a public API | Makes a Derived Product available to third parties (the service runs the model for them); a sweep of scenarios also reconstructs B1's table and the hazard curves | Low: not without written clearance |
| Sending private aggregates to a hosted AI service (the agent) | A third party unless the aggregates are already cleared as public research results; **whatever D1 clears for publication is also safe to show the agent, and nothing else is** | Medium |

Also relevant: the terms frame the Internal Purpose around "credit performance". Prepayment is
a performance outcome of the same assets, and the study treats credit dispositions as a
competing risk, but the owner may want that read confirmed. If any doubt remains, the
lowest-cost action is to write to Freddie Mac's loan-level data contact describing the intended
public outputs (aggregate evaluation tables, noncommercial, no artifacts) and asking for
confirmation in writing. A reply takes time but removes the risk from the project's largest
remaining blocker.

**Bottom line.** Addition A (published aggregates) is permitted on the most natural reading of
the research exception, pending the owner's decision. Addition B as live serving or artifact
publication is not, absent an agreement. B-lite sits with A.

## 7. Addition A: design

**Principle.** The public site gains a *research chapter* that is a faithful, aggregate-only
rendering of the sealed first evaluation, labeled with the evidence class and window role of
every number, built so that the agent never reads a real value.

**Pipeline (new code, synthetic-first):**

1. `prepay research export --run <REF> --diagnostics <probes> --out research/published/<run_id>/`
   - read-only on the run: it verifies `seal.json`, recomputes the candidate digest and the
     SHA-256 of `evaluations/first.json`, and records all three in the export so the public
     JSON is traceable to the sealed artifacts (the digests are already public in R2 G1);
   - refuses an experiment run's opened-window metrics unless `--exploratory` is passed, and
     then stamps every table with the ADR 0009 banner;
   - copies **only allowlisted fields** (§5 items 2-11), re-applies the 25-loan suppression,
     rounds to a stated precision, strips every path and run-local name, and derives the public
     presentation values (regime joins from public PMMS, quintile A/E from the bins, month-block
     intervals from the monthly series, the T1-T6 scorecard);
   - writes `evaluation.json`, `development.json` (optional), `forward-registration.json`
     (paths stripped) and a `manifest.json` with `synthetic`, `evidence_class`, source digests,
     export time, Git SHA and an empty `approval` block.
2. A JSON schema and a CI validator (`tests/unit/test_research_export.py`): required labels,
   suppression, no loan-identifier or path patterns, bounded sizes, every number finite, the
   `approval` block present whenever `synthetic` is false.
3. The publication gate learns the research directory: files there must pass the validator;
   any file with `synthetic: false` outside it is a finding.
4. `GET /api/research` serves the committed export (the live app), and the static export copies
   it to `data/research/` (the site). Both show the synthetic export when no approved real
   export is committed, under a "synthetic placeholder" banner, so CI and the browser tests
   exercise the view end to end on fictional data.
5. `web/src/views/Research.tsx`: the thirteen items of §5 with the B+ visual system, text
   alternatives and table twins for every chart, mobile layouts, axe-clean in both themes,
   and Playwright reconciliation of every displayed number to the served JSON (as
   `reconcile.spec.ts` does for the Scenario Lab).
6. Documentation: this ADR accepted; `docs/VALIDATION_REPORT.md` gains a real-data section
   that points at the view; `docs/STATUS.md` records the publication record; README states
   plainly that the real-trained model failed and is not a forecaster.

**Owner-run steps, when D1 is decided:** run the export on REF (minutes, a few MB of JSON),
read it, and if it is approved commit it (or hand it to the agent to commit; `git add` reveals
nothing to the agent, and the validator and gate run in CI). Until then the view carries the
synthetic placeholder and says so.

**Acceptance evidence (synthetic, in CI):** schema and gate tests; export reproducibility (same
run, same bytes); the view's reconciliation tests; static-vs-live parity; axe; the publication
scan on the site. **Real-data evidence:** the digest chain in the manifest, verified by the
owner against the private run; the owner's approval record.

**Risks.** (i) The owner's review is the only human check that the aggregates are what the
schema says; the validator catches shape, not meaning. (ii) The real-data headline is a failure;
the view must say "failed across rate regimes; not a forecaster" above the fold, or it misleads
in the other direction. (iii) Readers may treat a past-regime error as a forecast interval; every
interval is labeled by what it resamples.

## 8. Addition B: assessment by model

| | REF (M1+T, B1, B2, B0) | DEV2017 (X1-X3, H1) | REFIT2026 (R-M1, R-B2, R-X2, R-H1) |
|---|---|---|---|
| Historical performance | Opened once: **failed** pre-registered checks across regimes (owner-reported) | Tune/calibrate metrics on 2018/2019 and one development fold only; **no holdout result exists and none can exist before the forward opening** | In-sample through 2024-06; its tune and calibrate windows are the last two opened years; **no out-of-sample evidence** |
| Support for today's pools | Trained on ≤ 2017 rates (3.3-8.6%); a 3% coupon pool at a 7.3% market is about -430 bp incentive, outside training support; expect `unsupported`/`extrapolating` verdicts on the 2020-21 pools and `extrapolating` on the 2023 pool | Same training window as REF | Covers the 2022+ regime; a 5% sample |
| Stability | D6 sample and D7 seed stability **not measured** (G16 did not run) | same | same |
| Forward status | Registered reference | Registered member | Registered member |
| Terms, if served | Derived Product to third parties | same | same |
| Artifact risk, if published | LightGBM trees; B2 coefficients; **B1 cell frequencies**; preprocessor statistics | LightGBM trees; H1 coefficients | same as REF plus R-H1 |
| Verdict | **No live serving.** Precomputed research projections on fictional pools: conditional go (B-lite) | **Private until the forward opening.** Publishing its projections now would present an unconfirmed candidate as a product | **Private until the forward opening.** Serving it would present an unvalidated model as if current |

**Security and privacy of a live research endpoint, had it been permitted:** the API's custom
paths (up to 360 months) and parallel shocks let a client sweep the model's response surface and
reconstruct B1's table and each family's hazard curve, which is model extraction of a Derived
Product; the in-process rate limiter is per instance; hosting needs an owner account (L1); the
support profile shipped with a bundle contains training quantiles and cell counts. None of these
is a defect of the code. They are reasons that the current synthetic-only boundary (ADR 0005)
is the right one for a real-trained model.

**Would any of this contaminate the forward test?** No, provided the sealed members and the
registration are untouched, which their digests enforce (`load_registration().verify()` refuses
any change). The real contamination risk is social: a public exhibit of a candidate before its
one confirmatory test invites pre-judging and "fixing", and ADR 0010 §8 would make any fixed
model a late candidate anyway. That is why candidates stay private until the opening.

**B-lite, concretely:** `prepay research project --run <REF> --rates <FRED PMMS through 2026-06>`
projects the four fictional pools on the 13-scenario grid with REF's families, the ADR 0009 §7
verdict from REF's own support profile, the F2 credit assumption, and the audited ledger, and
writes the same static JSON shapes the site already serves. The site then offers a "research
model" toggle in the Scenario Lab and the Portfolio Explorer that is **off by default**, banner
labeled "trained on Freddie Mac data, privately; failed pre-registered checks; shown for study,
not forecasting", with the verdict above the headline as today. Value: it is the only place a
reader can see a model fitted to real loans respond to a rate shock on a realistic pool, and
see the applicability monitor fire on real support. Cost: moderate; the export, the toggle,
reconciliation tests. Gate: D1 and D3.

## 9. What should remain private

- Raw archives, bronze, silver and gold tables, the warehouse, the data lock's file digests.
- Every run directory: model files (LightGBM text, coefficients, B1 tables), preprocessor
  statistics, `feature_support`, validation details beyond the exported subset, manifests
  with machine paths.
- `diagnostics-primary.support.json` joint-cell counts; the rehearsal reports; the lockbox
  rehearsal; `logs/`; the private notes; `REAL_DATA_REVIEW_PACKET.md` as written.
- DEV2017, REFIT2026 and fold outputs, until the forward opening (then: as E1/E2 context next
  to the E3 result, never as the result).
- The exploratory post-opening reports, unless the owner chooses to publish them under the
  banner.
- Anything the owner's review flags, whatever the schema says.

## 10. What this proposal preserves, and how that is enforced

| Preserved | Enforcement |
|---|---|
| REF run, seal, `evaluations/first.json` | Never written; the export verifies the seal and records the first-evaluation SHA-256; R2 G1 digests are the reference |
| DEV2017 and REFIT2026 seals; the registration of 2026-11-02 | Never written; `forward register` is write-once; `verify()` refuses any change; no `forward evaluate` before a lock with cutoff ≥ 2027-06 |
| No interim look at forward months | No release after 48 is downloaded for this work; the evaluator refuses fewer than 12 forward months |
| No re-scoring of opened windows to revise a claim | Addition A reads the sealed report; B-lite scores fictional pools, not real loans; candidates are not scored on 2020-26 |
| The synthetic demo and the finance engine | The bundle loader still refuses non-synthetic runs; research JSON is data for a view, not a model bundle; no change to `finance/`, `scenarios/projection.py`, `modeling/lockbox.py`, `evaluation/forward.py` |
| No unbounded model search | No training in A; none in B-lite; G15/G16 (D4) only completes the already-queued R2 jobs with the already-registered models |
| The no-read rule for the agent | The agent builds on synthetic exports; the owner runs and reviews every real export; the first real values the agent sees are the ones D1 clears |

## 11. What a credible release looks like

Written for the reader the owner wants to convince: a finance or model-risk reviewer who
distrusts polished demos. It is credible when every chart on the research page can be traced,
by digest, to a sealed artifact on the owner's machine; when the first thing it says is that the
model failed and where; when every baseline is shown; when every interval says what it
resamples; when the forward test is visible as a registered, dated, unopened commitment; and
when the site still says, everywhere, that no real-trained model is served and nothing is a
forecast. An independent review (O4) of the research page before or soon after publication
would turn "self-reported" into "reviewed", and is the single highest-leverage non-engineering
step.

## 12. Work plan, prioritized by value

Sizes: S under a day of agent work, M one to two days, L two to four days. Owner time is stated
separately. Nothing starts before the owner's decision.

| Order | Item | Size | Owner action | Depends on |
|---|---|---|---|---|
| 0 | Decisions D1-D5 (§14) | | decide | |
| 1 | **A1** Export, schema, validator, gate extension, synthetic fixture; `docs/RESEARCH_RUNBOOK.md` §10 with the exact commands | M | none | D2 |
| 2 | **A2** Research view (items 1-11 and 13 of §5), API route, static integration, reconciliation and e2e tests, docs | L | none | A1 |
| 3 | **A3** Owner runs the export on REF, reviews, approves; commit; Pages deploys; post-deploy browser check | S | about 1 hour of review | D1, A2 |
| 4 | **R2-fix** Bounded memory in the cohort backtest's dense prediction path (§13), with an output-identity test; resume support in `experiment rolling-origin` so fold 2007-12 is reused and 2009-12 is evaluated rather than retrained; rerun queue C | M + owner runtime (hours, unattended) | start the queue | D4 |
| 5 | **A4** Development-evidence section (item 12): folds and probes, under the E1 banner | M | run the export again, review | R2-fix, D1 |
| 6 | **B-lite** `research project`, research-model toggle, tests, labels | M | run and review (about 30 min) | A3, D3 |
| 7 | Independent review of the research page | | invite a reviewer (O4) | A3 |
| 8 | Forward chapter: the opening's report rendered in the same view, with the E3 label | M | lock, ingest, evaluate once (O2) | a release with cutoff ≥ 2027-06 |

Not in the plan, by the owner's instruction and this audit: retraining, new features, equity
proxies (O3), new candidates, any search for a better model, hosting a real-trained model.

## 13. Found during the audit

1. **Queue C stopped on 2026-11-03.** The detached rolling-origin job completed fold 2007-12,
   trained fold 2009-12, and then failed while evaluating it: a NumPy out-of-memory error in
   `design.dense` (`hstack`) under `models.py:_predict_block` for the B2 model, called from
   `cohort.py:model_hazards` in the development cohort backtest. The blind runner then crashed
   on digesting a printed fold name as a path, because the detached process still held the
   pre-fix code from 2026-10-30, so no status file was written and the stability jobs (G16)
   never ran. The agent learned this only from the runner's own sanitizer (exception class names
   and code locations), applied to the private log. Fixing it is engineering, not research:
   score the dense design in smaller blocks (the same kind of change as #28 and #30), with a
   test that the output is identical, and let `rolling-origin` resume from existing fold
   directories. `docs/reviews/R2_QUALITY_GATES.md` G15 should read FAILED (memory), G16
   NOT RUN, and `docs/STATUS.md` should stop saying "in progress".
2. **PR #38 was merged by the owner on 2026-11-05.** The visual milestone is on `main`; this
   proposal was written on a branch from it.
3. The repository has no code license (L3). Publishing research results noncommercially does
   not need one, but attribution text for the research chapter should be decided with it.

## 14. Decisions requested

- **D1. Terms position (O5).** (a) May aggregate evaluation results of the kind in §5, with
  the suppression and labels in §7, be published on the public site? (b) May the same cleared
  aggregates be shown to the agent? (c) Should the owner write to Freddie Mac for confirmation
  first? The agent can draft that letter.
- **D2. Build Addition A** on synthetic data now (A1, A2), with the real export gated on D1.
- **D3. Addition B.** Accept the no-go for live serving and artifact publication; approve or
  decline B-lite (precomputed REF projections on the fictional pools) after A3.
- **D4. Finish G15/G16** with the memory fix and resume (R2-fix), or stop queue C and record
  the folds as incomplete. Either way the quality-gate report is corrected.
- **D5. Scope amendment.** Confirm that A, R2-fix and (if chosen) B-lite are the only work
  reopened after ADR 0011/0012, and that research otherwise stays frozen.

## Consequences, if accepted

The public product gains a real-data research chapter whose every number traces to a sealed
artifact, and says plainly that the model failed. The synthetic demo, the finance engine, the
sealed runs and the forward registration are unchanged. No real-trained model is served and no
artifact derived from Freddie Mac data is published. The project's claim becomes "a
pre-registered real-data study, reported in full", which is both stronger and more honest than
"a forecaster". The confirmatory chapter waits for the forward opening.
