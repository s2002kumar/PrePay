# ADR 0014: E01, economic generalization across rate regimes: pre-registration and execution conditions

- Status: **proposed**, for the owner's review. Nothing here has run on real data. Once the
  owner accepts it, this ADR is fixed before the first E01 real-data job. After that job, any
  change needs a new experiment ID, and both results are reported (ADR 0009 §11).
- Date: 2026-11-07
- Scope: the first experiment of the Prepay 2.0 research phase (ADR 0011 amendment 1, ADR 0013
  decision D4). It completes the unfinished rolling-origin work (R2 gate G15) and the stability
  work (G16).
- Evidence class: **development (E1)** only. Real outcome months ≤ 2019-12.
- Author: the implementing agent, from the code and from public FRED rates. No real-data output
  was read (ADR 0009 §3).

## 1. Question

> When the rate environment of the evaluation period differs from the training period, which
> existing model family predicts payoffs best? Which economic design choice explains the
> difference?

| ID | Sub-question | Comparison | Hypotheses (RELIABILITY_PLAN §4) |
|---|---|---|---|
| Q1 | Do the factored families (X1–X3) and the constrained hazard (H1) generalize better than M1 and B2 when the regime shifts? Do they lose accuracy when it doesn't? | Each candidate vs M1, B2 and B1, on regime-shift folds and on control folds | H-SUP, H-ERA |
| Q2 | Which change matters? | X1 − M1 (rate levels removed) · X2 − X1 (burnout made monotone) · X3 − X2 (behavioral features) · H1 − X2 (hazard form, logit-linear tails) · H1 − B2 (constraints vs plain logistic) | H-ERA, H-BURN, H-MEDIA, H-SUP |
| Q3 | Does calibration transfer across regimes? | Payoff A/E by regime cell (ADR 0009 D4 rule) | H-CAL |
| Q4 | What does each error mean financially? | Cohort payoff incidence, pool factor and truncated WAL; behavior vs rate path (D5) | H-RATE |
| Q5 | Are the differences larger than sampling and seed noise? | D6 and D7 stability | H-SAMP |

## 2. What E01 can and cannot show

- **It can** rank and explain families on development data. It can also *nominate* a model for
  a separate, later forward registration (ADR 0010 §8).
- **It cannot** confirm an improvement. It cannot judge any model on 2020-01..2026-06 (opened by
  the primary lockbox) or on forward months. It changes nothing in the sealed primary run, in
  DEV2017, in REFIT2026, in the 2026-11-02 registration or in the public product.
- **Structural limit, known before any run.** The public rates below show that no development
  fold has evaluation rates above its training maximum. None has the deep negative incentives
  of 2022+. So E01 tests the *low-rate* failure (the 2020–21 underprediction) far better than
  the *lock-in* failure (the 2022+ overprediction). Its only rate-shock evidence comes from:
  - the 2013 taper tantrum, in fold 2011-12;
  - the 2018 rise, in fold 2017-12.

  Every statement E01 makes about lock-in is labeled weak.

## 3. Data, population and sample

- **Data.** The Release 48 data lock that every R2 run used, with its fingerprint recorded.
  Labels and population follow MODELING §2 and ADR 0003.
- **Training sample.** Whole loans by stable hash: fraction **0.1**, sample index **0** (the
  primary run's sample). The fraction is fixed for E01. A fold that doesn't fit in memory stops
  the queue. It is not refit at a smaller fraction under the E01 ID.
- **Other windows.** Tune, calibrate and evaluate windows are read in full.
- **Guard.** No outcome month after 2019-12 is read. A reader-spy test enforces this, as it does
  for V1 today.

## 4. Folds and their regime classification (public data, fixed now)

Windows follow ADR 0009 §4: train ≤ o−24, tune o−23..o−12, calibrate o−11..o, evaluate
o+1..o+24. All six folds have 24 evaluation months. Rates are the matched 30-year PMMS known at
the end of t−1, from `prepay.evaluation.regimes.rate_regime_facts`.

**Rule.** A fold is a *regime-shift* fold if either condition holds:
- in at least 25% of its evaluation months, the rate lies outside the training window's range;
- its largest 6-month rise or fall exceeds the training window's largest in that direction.

| Origin | Train (target months) | Train 30y range | Evaluate | Eval range | Eval months outside train range | 6-month change, train / eval (bp) | New-low months in eval | Class |
|---|---|---|---|---|---:|---|---:|---|
| 2007-12 | 1999-01..2005-12 | 5.24–8.62% | 2008-01..2009-12 | 4.78–6.52% | 10 of 24 below | −119..+103 / **−168**..+84 | 4 | **regime shift** |
| 2009-12 | 1999-01..2007-12 | 5.24–8.62% | 2010-01..2011-12 | 3.98–5.14% | **24 of 24 below** | −119..+103 / −85..+59 | 8 | **regime shift** |
| 2011-12 | 1999-01..2009-12 | 4.78–8.62% | 2012-01..2013-12 | 3.32–4.51% | **24 of 24 below** | −168..+103 / −59..**+111** | 7 | **regime shift** |
| 2013-12 | 1999-01..2011-12 | 3.98–8.62% | 2014-01..2015-12 | 3.66–4.48% | 11 of 24 below | −168..+103 / −51..+32 | 0 | **regime shift** |
| 2015-12 | 1999-01..2013-12 | 3.32–8.62% | 2016-01..2017-12 | 3.42–4.32% | 0 | −168..+111 / −53..+84 | 0 | control |
| 2017-12 | 1999-01..2015-12 | 3.32–8.62% | 2018-01..2019-12 | 3.58–4.86% | 0 | −168..+111 / −82..+66 | 0 | control |

Source: FRED `MORTGAGE30US` and `MORTGAGE15US`, retrieved 2026-11-07 (observations through
2026-11-05). Reproduce with the commands in §12.

- **2009-12 and 2011-12 are the closest analogues of 2020–21.** Every evaluation month in them
  is below anything in training.
- **The two control folds** say whether a candidate gives up accuracy when nothing shifts.

## 5. Families

Each family is fitted in every fold by the ADR 0004 and ADR 0009 rules:
- the grid is chosen on the tune window's log loss;
- the ADR 0004 §7 cross-fitted temperature decision is made on the calibrate window;
- each model is scored with its own calibration decision.

| Family | Role | Grid (ExperimentConfig defaults) |
|---|---|---|
| B0 PSA + constant train-window credit rate | reference (**new to the folds**) | — |
| B1 age × incentive lookup | reference | prior 200 |
| B2 spline multinomial logistic | candidate | C ∈ {0.01, 0.1, 1} |
| M1 LightGBM softmax | candidate | leaves ∈ {15, 63}, early stopping on tune |
| X1, X2, X3 factored LightGBM | candidates | leaves ∈ {15, 63} |
| H1 constrained hazard | candidate | L2 ∈ {1e-4, 1e-3, 1e-2} |

The designated model is B2. It has no role, because experiment runs never select.

## 6. Measures (per fold and model, on the full evaluation window)

| ID | Quantity | Unit | Uncertainty |
|---|---|---|---|
| M-LL | Multiclass log loss (**primary**) | nats per loan-month | Paired differences on identical rows. Two-way (loan × month) bootstrap, 1,000 replicates, fixed seed; loan-cluster interval reported alongside |
| M-BR | Brier score | per loan-month | As M-LL |
| M-AE | Payoff A/E overall, and in the bottom and top fifths of rows by predicted payoff (the T6 construction) | ratio | Two-way bootstrap of the ratio (**new**) |
| M-CPR | Monthly balance-weighted `full_payoff_only_CPR_proxy`: mean bias and MAE | pp of CPR per year | Month-block bootstrap of the 24 monthly errors (**new**) |
| M-REG | Payoff A/E per regime cell (ADR 0009 §5: level band, 6-month direction, new low) | ratio | Two-way bootstrap (**new**; V1 used loan-cluster) |
| M-CR | Credit events, A/E and PR-AUC, only where a window has ≥ 100 credit events | — | Descriptive |
| F-INC | Cohort active at the origin: Aalen–Johansen payoff incidence at 6/12/24 months vs the model, hindsight and as-of-flat rates, with ADR 0006 §10 censoring bounds | pp of loans | Existing loan bootstrap of the realized curve |
| F-RUN | Balance run-off: pool-factor error at 6/12/24 months, horizon-truncated WAL error, principal by component | pp of t0 balance; years | Existing loan bootstrap of the observed factor |
| F-ATT | D5 decomposition: behavioral error (hindsight − realized) and rate-path error (as-of − hindsight) | pp | — |
| F-TOL | ADR 0010 amendment 2 tolerances T1–T6, applied descriptively per fold | value and pass/fail | — |
| P-ECO | D2 probes of every fold model: incentive ICE, rate level at fixed incentive (+200 bp), burnout, tail | share of rows; relative change | — |
| P-SUP | D3: share of evaluation rows and balance outside, or thinly inside, the fold's training support | share | — |

The run-off "curtailment" line keeps its known bias (R2 defect 1). It is reported, not used.

## 7. Reading rules (fixed now; development evidence only)

- **R1, ranking.** For each fold:
  - rank by log loss;
  - report the mean rank, the worst-fold gap to the fold's best, and fold wins against B1,
    B2 and M1.

  A win is a two-way interval of the paired difference lying entirely below 0. No test is
  pooled across folds, which overlap and are serially dependent.
- **R2, generalization.** A candidate *generalizes better than M1* only if both hold:
  - its paired log-loss difference vs M1 is significantly negative in **at least 3 of the 4**
    regime-shift folds;
  - it is not significantly worse than M1 in either control fold.

  The same rule is applied against B2.
- **R3, attribution.** The five Q2 differences are reported per fold with two-way intervals.
  A change is *supported* when its difference is significantly negative in at least 3 of the 4
  regime-shift folds.
- **R4, calibration transfer** (the D4 rule, with two-way intervals). A family's calibration
  *transfers* if, in every fold, every regime cell with at least 50 payoffs has an A/E interval
  inside [0.8, 1.25].
- **R5, financial materiality.** The 12-month pool-factor error and the 24-month truncated-WAL
  error (hindsight) are flagged where they exceed the T3/T4 tolerances of ADR 0010 amendment 2.
  This is descriptive.
- **R6, noise.** A difference smaller than twice the larger of the two families' D6 sample SDs of
  log loss is *within sampling noise* (from §8). For a family without its own D6 measurement,
  the largest SD measured for any tree family is used.
- **R7, nomination.** A family is recommended to the owner as a late forward candidate only if:
  - R2 holds against M1;
  - it is never significantly worse than B2;
  - it leaves no D2 economic flag unexplained;
  - its R2 differences exceed R6 noise.

  If no family qualifies, E01 reports **no development evidence for a change**, and the product
  and its status stay as they are. Registering a nominated model is a separate owner decision.
  Its seen-through month would be the latest cutoff on its registration day, and only months
  after that could confirm it.

The E01 summary report computes R1–R7 itself and states each result as a field. A reader can
check the verdicts against the tables, and no rule is applied by hand.

## 8. Stability (G16)

Run on the DEV2017 windows with the ADR 0009 §6 rules unchanged: 5 replicates each, the
tune-window log loss, and the incentive response on a fixed 2% reference sample.

| Stage | Kind | Families | Status in this proposal |
|---|---|---|---|
| S1 | D6 loan samples | B2, M1, X2, H1 | as planned in R2 |
| S1 | D7 seeds | M1, X2 | as planned in R2 (B2 and H1 are deterministic convex fits) |
| S2 | D6 and D7 | X1, X3 | optional; owner decides after S1 |

## 9. Execution conditions

### 9.1 Provenance

- Every E01 private job runs from one clean worktree at one commit: the merge commit of
  Gate B. That commit is recorded in every manifest.
- The runner process starts fresh after that commit. Gate A found a detached process that kept
  code from before a fix (R2 defect 15).
- No V1 fold run is reused. Every fold is trained fresh under E01, at one code version, with B0
  included.
- The V1 runs stay where they are. Their one report (fold 2007-12) is listed in E01's
  provenance and never merged into E01's results.

### 9.2 Gate B: engineering on synthetic data, before any private job

| Item | Content |
|---|---|
| B1 | Fit B0 in development folds |
| B2 | Two-way intervals for payoff A/E (overall, fifths, regime cells); month-block interval for CPR bias; 1,000 replicates for paired differences; the five attribution pairs |
| B3 | D2 probes and D3 support shares per fold, inside the fold report |
| B4 | E01 summary: R1–R7 as computed fields; summary rewritten after every fold, so a stopped queue keeps the folds it finished |
| B5 | `--resume`. Reuses a completed **E01** fold only if its config digest, data-lock fingerprint, Git SHA and software-lock digest all match. Evaluates a fold that trained but has no evaluation |
| B6 | Runner (private tool) preflight. Before each job, refuse to start while host free commit is below the threshold; wait up to 2 hours, then stop. Copy only each fold report's `stages` block (seconds, peak working set, peak commit) into the status file |
| B7 | Synthetic dry run of the exact E01 commands on the synthetic dev world, with its time and peaks recorded; CI green |

### 9.3 Gate C: owner-run pilot on real data

1. **Host.** Docker Desktop and other heavy applications closed, and at least **12 GiB** of free
   commit at launch.
   - On 2026-11-07, with normal desktop use, the laptop had 9.6 GiB of free commit out of a
     63.4 GiB limit.
   - The runner re-checks before every job.
2. **Pilot: E01 fold 2007-12.** It has the smallest training window, and under V1 the same fold
   trained in about 54 minutes and evaluated in about 48. It passes only if all of these hold:
   - **Exit 0, peak commit ≤ 10 GiB.** That is the ADR 0006 §5 budget, now measured as commit,
     because Gate A showed that peak working set understates demand under paging.
   - **Reproduction.** The seven V1 families' model files and `preprocessor.json` have SHA-256
     digests equal to those of the V1 run `20261103T013552Z-V1-2007-12-d618e7d4`.
     - The dependency pins are identical between `dbcfb1d` and `main`; only the project's own
       version line changed in `uv.lock`.
     - The only training-path code change since then is the identity-tested encoder of #30.
     - Only digests are compared. A mismatch stops the queue until the cause is found.
   - **Implementation booleans.** The `experiment verify` checks hold: a coherent simplex on
     every scored row, a bit-identical reload, and monotonicity properties reported.
3. **Projection.** Before each later fold, the runner projects that fold's peak commit:
   - from the pilot's stage peaks, scaled by the fold's evaluation-window rows and training rows;
   - it prints only pass/fail and the projected GiB.

   If a projection exceeds the budget, the queue stops. The options then go to the owner:
   - score the window one model at a time (a Gate B+ change, identity-tested);
   - or run that fold alone on an otherwise idle host.

### 9.4 Gate D: the remaining folds, then stability

- Folds run in order: 2009-12, 2011-12, 2013-12, 2015-12, 2017-12.
- Then the summary, then S1 of §8 (samples, then seeds).
- **Stop conditions:**
  - any non-zero exit;
  - peak commit above the budget;
  - a failed projection;
  - the `STOP` file.
- Nothing changes automatically after a stop.

### 9.5 Expected cost (from measured private runs on the shared laptop)

| Job | Basis | Estimate |
|---|---|---|
| One fold: train | V1 fold 2007-12: 54 min. V1 fold 2009-12: 6.1 h, on the shared host. Later folds train on more years | 1–8 h each |
| One fold: evaluate | V1 fold 2007-12: 48 min | 1–2 h each, plus the new probes and 1,000-replicate intervals |
| All six folds | sum of the above | **15–50 h** of unattended wall time |
| G16 S1 | DEV2017 (4 families, ≤ 2017-12 training): 86 min per fit | **10–20 h** |

These are ranges from a host shared with unrelated work, not benchmarks. Peak memory at real
scale is unknown until the pilot measures it.

### 9.6 Who reads the results

ADR 0009 §3 is unchanged. The agent sees exit codes, times, stage peaks, digests, exception
class names and boolean implementation checks. **The owner reads the E01 report.** The agent can
therefore neither interpret E01's findings nor draft the research page's statistical summary
unless one of two things happens:
- the owner summarizes the results;
- or the owner amends ADR 0009 §3 to allow the agent to read E01's aggregate summary. That
  report holds suppressed cells and no identifiers, and the amendment ties to D1 and O5.

### 9.7 Outputs

- **Private:** `artifacts/experiments/e01/` (fold runs, `e01-summary-<UTC>.json`, stability
  reports) and `logs/e01/status/`.
- **Public:** the repository records process status only: ran or failed, dates, peaks and
  digests. Publishing any E01 aggregate follows decisions D1 and D2.

## 10. Decisions requested

| ID | Decision | Proposal |
|---|---|---|
| E01-D1 | Who interprets E01 | The owner reads the report, or amends ADR 0009 §3 for E01's aggregate summary |
| E01-D2 | Reading rules R1–R7 and their thresholds | Accept as written, or amend **before** any run |
| E01-D3 | Stability scope | S1 now; decide on S2 after S1 |
| E01-D4 | Host conditions and budget | At least 12 GiB free commit at launch; 10 GiB peak commit per job |
| E01-D5 | Retraining | Fresh E01 folds, with the fold 2007-12 reproduction pilot |
| E01-D6 | Start Gate B | Implement §9.2 on synthetic data and return its evidence before any private job |

## 11. Consequences

- The development evidence becomes complete: all six folds and stability, under one code
  version, with dependence-aware intervals throughout.
- The 2020–21 failure mode gets a real test on two strong analogues, 2010–11 and 2012–13. The
  lock-in mode stays weakly tested until forward months exist.
- Nothing E01 finds can be called a confirmed improvement. At most it nominates a model for a
  separate forward registration.

## 12. Reproduce the public facts in §4

```bash
uv run prepay rates fetch --out scratch/pmms
# FRED can take longer than the fetch timeout; then download
# https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US (and MORTGAGE15US) into scratch/pmms
uv run python docs/reviews/gate-a/fold_regimes.py scratch/pmms
```

The output recorded on 2026-11-07 is `docs/reviews/gate-a/fold-regimes.json`. A later FRED
download can differ only if FRED revises past weekly observations.
