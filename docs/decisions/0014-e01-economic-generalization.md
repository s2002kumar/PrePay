# ADR 0014: E01, economic generalization across rate regimes: pre-registration and execution conditions

- Status: **accepted with revisions** by the owner on 2026-11-09. The decisions are in §10 and
  the revisions in §13. This ADR is fixed before the first E01 real-data job. After that job, a
  change needs a new experiment ID, and both results are reported (ADR 0009 §11).
- Date: 2026-11-07 (proposal), 2026-11-09 (revision and acceptance)
- Scope: the first experiment of the Prepay 2.0 research phase (ADR 0011 amendment 1, ADR 0013
  decision D4). It completes the unfinished rolling-origin work (R2 gate G15) and the stability
  work (G16).
- Evidence class: **development (E1)**, real outcome months ≤ 2019-12. Every E01 result,
  report and table carries that label.
- The forward study is **unchanged**. That covers ADR 0010, the 2026-11-02 registration, its
  members and `evaluation/forward.py`. E01 neither reads nor modifies any of them.
- Author: the implementing agent, from the code and from public FRED rates. No real-data output
  was read (ADR 0009 §3).

## 1. Question

> In development data, which existing model families show consistently lower out-of-sample
> error when the evaluation period's rates lie outside the training period's range? How do
> their bundled design choices compare?

E01 is **exploratory**. It describes consistency across a few overlapping folds. It proves
neither economic generalization nor the cause of a difference.

| ID | Sub-question | Comparison |
|---|---|---|
| Q1 | Do X1–X3 and H1 have lower log loss than M1 and B2 on regime-shift folds, without losing accuracy on control folds? | Families F-M1 and F-B2 (§6) |
| Q2 | How do the bundled designs compare? | Family F-DESIGN (§6), read as bundles (§7, R3) |
| Q3 | Does calibration transfer across regimes? | Payoff A/E by regime cell (ADR 0009 D4 rule) |
| Q4 | What does each error mean financially? | Cohort payoff incidence, pool factor, truncated WAL; behavior vs rate path (D5) |
| Q5 | How sensitive are results to the loan sample and the seed? | D6/D7 stability, a robustness diagnostic |

## 2. What E01 can and cannot show

- **It can** describe how families rank and how consistently they differ on development folds.
  It can also *nominate* a model for a separate, later forward registration (ADR 0010 §8).
- **It cannot** confirm an improvement. It cannot show how any model performed, or would
  perform, on 2020-01..2026-06 or on forward months. The fold regime classes in §4 are
  *analogues* of those periods, not evidence about them.
- **It cannot attribute a difference to one cause.** Most compared pairs differ in several
  design choices at once (R3).
- **It changes nothing in:** the sealed primary run, DEV2017, REFIT2026, the forward
  registration or the public product.
- **Structural limit, known before any run** (§4). No fold has evaluation rates above its
  training maximum, and none has the deep negative incentives of 2022+. E01 therefore studies
  the low-rate failure (2020–21) far better than lock-in (2022+). Every statement about
  lock-in is labeled weak.

## 3. Data, population and sample

- **Data.** The Release 48 data lock that every R2 run used. Its fingerprint is recorded, and
  the population and labels follow MODELING §2 and ADR 0003.
- **Outcome months.** Only months ≤ 2019-12 are read; a reader-spy test enforces this.
- **Training sample.** Whole loans by stable hash, fraction **0.1**, sample index **0** (the
  primary run's sample). The fraction is fixed for E01. A fold that doesn't fit stops the
  queue; it is never refit at another fraction under the E01 ID.
- **Other windows.** Tune, calibrate and evaluate windows are read in full.

## 4. Folds and regime classes (public data, fixed now)

Windows follow ADR 0009 §4: train ≤ o−24, tune o−23..o−12, calibrate o−11..o, evaluate
o+1..o+24. Rates are the matched 30-year PMMS known at the end of t−1.

**Rule.** A fold is a *regime-shift* fold if either condition holds:
- in at least 25% of its evaluation months, the rate lies outside the training range;
- its largest 6-month rise or fall exceeds the training window's largest in that direction.

| Origin | Train | Train 30y range | Evaluate | Eval range | Eval months outside train range | 6-month change, train / eval (bp) | New-low months in eval | Class |
|---|---|---|---|---|---:|---|---:|---|
| 2007-12 | 1999-01..2005-12 | 5.24–8.62% | 2008-01..2009-12 | 4.78–6.52% | 10 of 24 below | −119..+103 / **−168**..+84 | 4 | **regime shift** |
| 2009-12 | 1999-01..2007-12 | 5.24–8.62% | 2010-01..2011-12 | 3.98–5.14% | **24 of 24 below** | −119..+103 / −85..+59 | 8 | **regime shift** |
| 2011-12 | 1999-01..2009-12 | 4.78–8.62% | 2012-01..2013-12 | 3.32–4.51% | **24 of 24 below** | −168..+103 / −59..**+111** | 7 | **regime shift** |
| 2013-12 | 1999-01..2011-12 | 3.98–8.62% | 2014-01..2015-12 | 3.66–4.48% | 11 of 24 below | −168..+103 / −51..+32 | 0 | **regime shift** |
| 2015-12 | 1999-01..2013-12 | 3.32–8.62% | 2016-01..2017-12 | 3.42–4.32% | 0 | −168..+111 / −53..+84 | 0 | control |
| 2017-12 | 1999-01..2015-12 | 3.32–8.62% | 2018-01..2019-12 | 3.58–4.86% | 0 | −168..+111 / −82..+66 | 0 | control |

FRED `MORTGAGE30US` and `MORTGAGE15US`, retrieved 2026-11-07, observations through 2026-11-05.
Reproduce with §12.

- **All four shift folds are low-rate shifts.** Folds 2009-12 and 2011-12 resemble 2020–21 in
  that respect only. Housing, credit and policy conditions differed, so the class is an
  analogue, not a test of 2020–21.

## 5. Families

Each family is fitted per fold by the ADR 0004/0009 rules:
- its grid setting is chosen on the tune window's log loss;
- the ADR 0004 §7 cross-fitted temperature decision is made on the calibrate window;
- it is scored with its own calibration decision.

| Family | Role | Grid |
|---|---|---|
| B0 PSA + constant train-window credit rate | reference (**new to the folds**) | — |
| B1 age × incentive lookup | reference | prior 200 |
| B2 spline multinomial logistic | candidate | C ∈ {0.01, 0.1, 1} |
| M1 LightGBM softmax | candidate | leaves ∈ {15, 63}, early stopping on tune |
| X1, X2, X3 factored LightGBM | candidates | leaves ∈ {15, 63} |
| H1 constrained hazard | candidate | L2 ∈ {1e-4, 1e-3, 1e-2} |

## 6. Measures, effect sizes and uncertainty

Every measure is computed per fold and model on the full evaluation window.

**Paired log loss (primary).**
- The difference is d = candidate − reference, in nats per loan-month, on identical rows.
  Negative means the candidate has lower loss.
- It is reported two ways:
  - as the absolute effect;
  - as the relative effect, d divided by the reference's mean log loss in that fold.
- Uncertainty comes from a two-way (loan × month) pigeonhole bootstrap with 1,000 replicates
  and a fixed seed. Each comparison reports:
  - the bootstrap standard error;
  - an **unadjusted** 95% percentile interval (descriptive);
  - a **simultaneous** 95% interval for its comparison family (below).

**Comparison families.** Each is controlled for familywise error at 5% by Bonferroni.

| Family | Comparisons | m |
|---|---|---:|
| F-M1 | B2, X1, X2, X3, H1 vs M1, in each of 6 folds | 30 |
| F-B2 | M1, X1, X2, X3, H1 vs B2, in each fold | 30 |
| F-DESIGN | X1−M1, X2−X1, X3−X2, H1−X2, H1−B2, in each fold | 30 |

- **The simultaneous interval** is the Wald interval d ± z(1 − 0.05/(2m)) × SE, with z ≈ 3.14
  for m = 30.
  - A percentile interval at that level would need far more than 1,000 replicates to place its
    tails.
  - The bootstrap standard error is well estimated by 1,000.
- **References.** Comparisons against B0 and B1 are descriptive only, with unadjusted
  intervals and no inferential claim.
- **Classification of each family comparison**, from its simultaneous interval [L, U]:

| Class | Condition | Meaning |
|---|---|---|
| lower loss | U < 0 | the candidate has lower loss |
| higher loss | L > 0 | the candidate has higher loss |
| non-inferior | 0 ≤ U < δ | the candidate is no worse than the margin; lower loss is not shown |
| inconclusive | otherwise | neither shown. **This is not evidence of equivalence or of non-inferiority** |

- **Non-inferiority margin δ** = 0.5% of the reference's mean log loss in that fold.
  - This is an engineering judgment, fixed now.
  - It is small next to the 1–5% gaps between families seen on synthetic validation data.
  - The owner may amend it before the first E01 run.

**Other measures** (intervals are unadjusted and descriptive unless stated):

| ID | Quantity | Unit | Uncertainty |
|---|---|---|---|
| M-BR | Brier score | per loan-month | descriptive |
| M-AE | Payoff A/E overall, and in the bottom and top fifths of rows by predicted payoff | ratio | two-way bootstrap of the ratio |
| M-CPR | Monthly balance-weighted `full_payoff_only_CPR_proxy`: mean bias and MAE | pp of CPR per year | month-block bootstrap of the 24 monthly errors |
| M-REG | Payoff A/E per regime cell (ADR 0009 §5) | ratio | two-way bootstrap |
| M-CR | Credit events, A/E and PR-AUC, only where ≥ 100 credit events | — | descriptive |
| F-INC | Cohort at the origin: Aalen–Johansen payoff incidence at 6/12/24 months vs the model, hindsight and as-of rates, with censoring bounds | pp of loans | existing loan bootstrap |
| F-RUN | Balance run-off: pool-factor error at 6/12/24 months, horizon-truncated WAL error, principal by component | pp of t0 balance; years | existing loan bootstrap |
| F-ATT | D5: behavioral error and rate-path error | pp | — |
| F-TOL | ADR 0010 amendment 2 tolerances T1–T6, computed by the forward study's own definitions, read-only | value and pass/fail | descriptive |
| P-ECO | D2 probes of every fold model | share; relative change | — |
| P-SUP | D3 share of evaluation rows outside or thinly inside training support | share | — |

The run-off "curtailment" line keeps its known bias (R2 defect 1). It is reported, not used.

## 7. Reading rules (fixed now; exploratory, development evidence only)

The E01 summary computes every rule below and states each result as a field. Each statement
carries the label "development evidence (E1); exploratory".

- **R1, description.** For each fold:
  - rank families by log loss;
  - report the mean rank and the worst-fold gap to the fold's best;
  - count the F-M1 and F-B2 classes per candidate.

  Ranks are point estimates, not tests.
- **R2, consistency vs M1.** A candidate *shows a consistent advantage over M1 on regime-shift
  folds* if both hold:
  - in F-M1 it is classed **lower loss** in at least 3 of the 4 regime-shift folds;
  - it is **non-inferior** (or lower loss) in both control folds.

  If the first part holds but a control fold is inconclusive, the result reads "advantage on
  shift folds; control-fold loss not ruled out".
  - **What R2 is:** a consistency pattern across four overlapping, serially dependent, all
    low-rate shift folds.
  - **What R2 is not:** a demonstration of economic generalization. No inference is pooled
    across folds.

  The same rule is computed against B2 in F-B2.
- **R3, design-bundle comparisons.** Each F-DESIGN pair compares bundles of choices, not single
  causes. Every pair also differs by its own tuning outcome.

  | Pair | What differs |
  |---|---|
  | X1 − M1 | Factored two-booster structure vs joint softmax; removal of `market_rate_t1`, `note_rate_pct` and `pmms_application_based` from both boosters; payoff hazard non-decreasing in incentive |
  | X2 − X1 | Only the burnout constraint (payoff hazard non-increasing in burnout). The closest to a single-choice contrast |
  | X3 − X2 | Three derived behavioral features (new opportunity, new five-year low, payment saving %), each constrained non-decreasing |
  | H1 − X2 | Functional form (penalized logistic with piecewise-linear terms vs trees); tail behavior (logit-linear vs flat); feature set (H1 drops loan size and remaining payments, adds new opportunity, uses hinge and seasonal terms); credit model |
  | H1 − B2 | Factored vs joint form; monotone constraints; no rate levels or loan size; different bases and features |

  A pair *shows a consistent difference* when it has the same class (lower or higher loss) in
  at least 3 of the 4 regime-shift folds. No difference is attributed to the removal of rate
  levels or to any single constraint. That would need a controlled ablation, which E01 doesn't
  run.
- **R4, calibration transfer** (the D4 rule, a diagnostic). A family's calibration *transfers*
  if, in every fold, every regime cell with at least 50 payoffs has an unadjusted two-way A/E
  interval inside [0.8, 1.25].
- **R5, financial materiality** (descriptive). The 12-month pool-factor error and the 24-month
  truncated-WAL error (hindsight rates) are flagged where they exceed the ADR 0010 amendment 2
  T3/T4 tolerances.
- **R6, stability** (a robustness diagnostic, never a test or gate).
  - For each family **measured in S1**, the SD of tune-window log loss across loan samples
    (D6) or seeds (D7) is reported next to that family's fold effect sizes.
  - An effect smaller than the measured SD of either family in the pair is marked "fragile to
    sampling".
  - A family without an S1 measurement is marked "not measured". No SD is imputed from another
    family.
- **R7, nomination** (a recommendation to the owner). A family is nominated as a late forward
  candidate only if all of these hold:
  - R2 holds against M1;
  - it is never classed **higher loss** than B2 in F-B2;
  - it leaves no D2 economic flag unexplained.

  R6 is reported beside it as context, not as a condition. If no family qualifies, E01 reports
  **no development evidence for a change**. Registration is a separate owner decision, judged
  only on months after its own seen-through date.

## 8. Stability (G16)

S1 runs on the DEV2017 windows with the ADR 0009 §6 measurements: 5 replicates; tune-window
log loss; incentive response on a fixed 2% reference sample. The ADR 0009 §6 flag thresholds
are reported as diagnostics, not gates.

| Stage | Kind | Families | Status |
|---|---|---|---|
| S1 | D6 loan samples | B2, M1, X2, H1 | approved (E01-D3) |
| S1 | D7 seeds | M1, X2 | approved (E01-D3). B2 and H1 are deterministic convex fits |
| S2 | D6 and D7 | X1, X3 | conditional on S1's findings; a separate owner decision |

## 9. Execution conditions

### 9.1 Provenance

- **One commit.** Every E01 private job runs from one clean worktree at one commit, recorded
  in every manifest. A dirty tree is refused for real data.
- **Fresh processes.** Each job (a fold, or a stability kind) runs in its own child process.
  - Its peak memory is then its own.
  - A queue never keeps code from before a change (R2 defect 15).
- **Fresh training.** No V1 fold run is reused; every E01 fold is trained fresh, with B0
  included. The V1 runs stay where they are, listed as provenance, and are never merged into
  E01's results.
- **Resume rule.** Resume reuses only **E01** fold runs whose provenance matches exactly:
  - E01 configuration digest;
  - data-lock fingerprint;
  - Git SHA;
  - software-lock, feature-contract and derived-feature digests.

  Any mismatch is refused, never reconciled.

### 9.2 Gate B: engineering on synthetic data (approved, E01-D6)

| Item | Content |
|---|---|
| B1 | B0 in the development folds |
| B2 | §6 effect sizes, unadjusted and simultaneous intervals, families and classes; A/E and CPR intervals; regime cells with two-way intervals |
| B3 | D2 probes and D3 support shares per fold |
| B4 | The deterministic E01 summary with R1–R7 as computed fields, and a local, deterministic, human-readable report built from it for the owner (E01-D1) |
| B5 | Resume and provenance safeguards (§9.1) |
| B6 | Orchestration: preflight of free commit before each job; per-job budget check; STOP file; a metadata-only job ledger (exit codes, times, memory, digests, reproduction booleans) that the agent may read |
| B7 | An exact synthetic dry run of the E01 commands, with each job's time and memory; CI green |

**Memory labels.**
- The `stages` entries of a fold report are **process high-water marks**: the peak since the
  process started, read after each stage. They are not per-stage peaks, and are never added
  or projected as if independent.
- A job's resource figure is its child process's peak commit (peak RSS where commit isn't
  available).

### 9.3 Gate C: owner-run pilot on real data (not yet authorized)

1. **Host.** At least **12 GiB** free commit at launch, checked before every job (E01-D4).
2. **Pilot: E01 fold 2007-12.** It passes only if all of these hold:
   - **Exit 0, peak commit ≤ 10 GiB** (E01-D4).
   - **Byte identity.** SHA-256 digests of the seven V1 families' model files and
     `preprocessor.json` equal those of V1 run `20261103T013552Z-V1-2007-12-d618e7d4`. Only
     the digests are compared.
   - **On a mismatch** the queue stops and the cause is investigated (E01-D5). The queue
     continues only with an explicit, written waiver from the owner, recorded in the ledger
     and the summary. Nothing is waived silently.
   - **Boolean implementation checks** (`experiment verify`) all pass.
3. **Advisory projection before each later fold.**
   - Projected peak = pilot baseline + (pilot peak − pilot baseline) × the largest of the
     fold's row ratios to the pilot (training rows, evaluation rows). This scales everything
     above baseline, which over-projects.
   - If the projection exceeds the budget, the queue stops before that fold, and the owner
     decides.

### 9.4 Gate D (not yet authorized)

- Folds 2009-12 to 2017-12 in order, then the summary, then S1.
- **Stop conditions:**
  - any non-zero exit;
  - a job above the budget;
  - a failed preflight after a 2-hour wait;
  - a stopping projection;
  - the `STOP` file.
- Nothing changes automatically after a stop.

### 9.5 Expected cost (measured private runs, shared laptop)

| Job | Basis | Estimate |
|---|---|---|
| One fold: train | V1 fold 2007-12 took 54 min; V1 fold 2009-12 took 6.1 h | 1–8 h each |
| One fold: evaluate | V1 fold 2007-12 took 48 min | 1–2 h each, plus probes and intervals |
| Six folds | | **15–50 h** unattended |
| S1 | DEV2017 took 86 min per 4-family fit | **10–20 h** |

### 9.6 Who reads the results (E01-D1)

- **Only the owner interprets private results.** No restricted numerical result goes to a
  hosted AI service.
- **The agent sees only the job ledger:** exit codes, times, memory, digests, reproduction
  booleans and exception class names.
- **The owner reads the local report.** `prepay experiment e01 report` writes it from the
  summary, deterministically. It explains every predefined metric, class and flag in fixed
  wording, with no model or service involved.

### 9.7 Outputs

- **Private:**
  - `<out>/e01/` holds the fold runs, stability runs, `e01-summary.json` and the local
    report;
  - `<out>/e01/ledger.json` is metadata only.
- **Public:** process status only. Publication of any E01 aggregate follows ADR 0013 D1/D2,
  and is blocked pending the permissions decision.

## 10. Owner decisions (2026-11-09)

| ID | Decision |
|---|---|
| E01-D1 | Only the owner interprets private results. Build a useful local, deterministic report of the predefined metrics and flags. No restricted numerical result goes to hosted AI |
| E01-D2 | R1–R7 approved with the revisions in §13 |
| E01-D3 | S1 approved; S2 conditional on S1's findings |
| E01-D4 | 12 GiB free-commit preflight; 10 GiB peak-commit budget per job |
| E01-D5 | Fresh E01 retraining, and one byte-identity pilot on fold 2007-12. Any mismatch is investigated, not silently waived |
| E01-D6 | Gate B engineering and synthetic testing only. No private real-data job yet |

## 11. Consequences

- The development comparison becomes complete under one code version. Its uncertainty is
  dependence-aware, and its multiple comparisons are controlled.
- Its findings stay exploratory and development-only. At most they nominate a model for a
  separate forward test, which remains the only route to confirmation.

## 12. Reproduce the public facts in §4

```bash
uv run prepay rates fetch --out scratch/pmms
# FRED can take longer than the fetch timeout; then download
# https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US (and MORTGAGE15US) into scratch/pmms
uv run python docs/reviews/gate-a/fold_regimes.py scratch/pmms
```

The output recorded on 2026-11-07 is `docs/reviews/gate-a/fold-regimes.json`.

## 13. Revisions (owner review, 2026-11-09)

1. **R2 and R3 describe exploratory consistency**, not proof or attribution.
   - Inferential statements now come from Bonferroni-simultaneous intervals within three
     declared families.
   - Effect sizes (absolute and relative) and uncertainty are reported for every comparison.
   - A non-inferiority margin separates "non-inferior" from "inconclusive".
2. **The compared pairs are bundles.** X1−M1 and H1−X2 are treated as comparisons of bundled
   designs, and each pair's differences are listed. No single cause is attributed without a
   controlled ablation.
3. **R6 is a robustness diagnostic.** No SD is imputed across families, and R6 is no longer a
   condition of R7.
4. **Memory peaks are labeled.** Stage memory figures are process high-water marks. The
   projection scales whole-job peaks conservatively and doesn't treat stages as independent.
5. **Development labels everywhere.** Every E01 result is labeled development evidence, and the
   regime classes are analogues, not confirmation of 2020–2026.
6. **The forward study is unchanged:** ADR 0010, the registration and `evaluation/forward.py`.

## 14. Clarifications from Gate B (2026-11-10): execution only

Gate B built and exercised §9 on synthetic data. These points make the execution conditions
precise. None changes a family, measure, interval, class, margin or reading rule.

1. **"Pilot baseline" (§9.3)** is the job's commit charge after it has imported its libraries
   and before it reads any data. It is recorded as `baseline_commit_bytes`.
   - Measuring from the command's start scaled about 1.4 GiB of imports as if it grew with the
     data.
   - In the dry run that stopped a fold projected at 10.2 GiB, when no fold had peaked above
     1.9 GiB.
2. **Implementation checks run after every fold, not only the pilot.** This is stricter than
   §9.3.
   - The command is `prepay experiment verify --unsealed`. E01 folds are never sealed, so only
     the seal check is omitted.
   - A failed check stops the queue (exit 8). Only the names of failed checks reach the
     ledger.
3. **One orchestrator per E01 directory.** `e01 run` holds `.e01-run.lock` for the whole stage.
   - On Windows, stopping a shell leaves its child processes running. In the dry run, two
     orchestrators wrote the same directory.
   - A lock left by a crash is never removed automatically.
4. **STOP.** The `STOP` file also ends a preflight wait, at the next poll.
5. **Standby.** The host must not sleep during a stage. Standby pauses jobs without harming
   them, but wall times then include it: one dry-run fold showed 12.7 h for about 13 min of
   work.
6. **R7 and the factored families.** X1–X3 can show `incentive_ice_violations` on the final
   payoff probability `(1 − c) h`. This is the known property of ADR 0010 amendment 2. R7
   lists it under "D2 flags to explain" and leaves the explanation to the owner. It is not
   treated as explained automatically.
