# ADR 0004: Model families, validation-only selection, calibration and the sealed lockbox

- Status: accepted (pre-registered before any holdout evaluation on real data)
- Date: 2026-10-28
- Scope: `src/prepay/modeling/`; implements MODELING §5–§9 without changing them

## Decisions

1. **Coherent outputs.** Every model returns `(active, prepay, credit)` probabilities and
   `check_simplex` rejects any row that is not a simplex. Nothing is clipped. M1 is one LightGBM
   multiclass softmax, not two binary models with `p + d` clipped.
2. **Families.** B0 = 100% PSA payoff SMM by age plus a constant train-period credit rate
   (reference only). B1 = age (7 bins) × incentive (7 bins) empirical frequencies, shrunk to
   the marginal with a Dirichlet prior of 200 pseudo-observations. B2 = L2 multinomial logistic
   regression over standardized numerics, one-hot categoricals (explicit missing/other) and cubic
   B-splines (knots at train quantiles) for age, incentive and burnout. M1 = LightGBM multiclass,
   deterministic settings, native categorical handling.
3. **No reweighting or oversampling.** Rare credit dispositions keep their true prevalence, so
   probabilities stay calibrated. Imbalance is reported (prevalence, PR-AUC, per-class ECE),
   not hidden.
4. **Artifacts are JSON or LightGBM text, never pickle.** Loading a run can't execute code. B2
   inference is plain NumPy from stored coefficients, checked against scikit-learn to 1e-12.
5. **Tuning on Validation A.** This covers B2's L2 strength, M1's `num_leaves`, and M1's early
   stopping. Selection on the same window is somewhat optimistic for M1. That's accepted and
   disclosed rather than spending Validation B on it.
6. **Selection rule (parsimony).** Among B1, B2 and M1, take the *simplest* whose Validation A log
   loss is not significantly worse than the best (95% loan-clustered bootstrap interval of the
   paired difference includes 0).
   *Observed trade-off:* on the small CI synthetic dataset (79 validation events) the rule chose
   B1, although B2 had lower validation loss and recovered the synthetic truth better. This is
   the cost of a parsimony rule on an underpowered validation window. With real-data volumes
   the intervals narrow. The rule is kept as written and not adjusted after seeing results.
7. **Calibration.** Temperature scaling of the selected model is adopted only if a temperature fit
   on one loan-hash half of Validation B lowers log loss on the other half, in both directions.
   The adopted temperature is then refit on all of Validation B. Test data is never used.
8. **Primary metric:** multiclass log loss on the at-risk panel. Secondary: Brier, per-class
   ECE and reliability, prepay AUROC, credit PR-AUC, and the balance-weighted
   `full_payoff_only_CPR_proxy` bias/MAE in CPR percentage points. Intervals resample loans.
9. **Holdout guard.** `read_window` refuses test windows unless given a seal that verifies against
   the run's current artifacts. A test spies on the panel reader during training and asserts
   nothing after 2019-12 is requested.
10. **Seal and lockbox.** `prepay seal` writes `seal.json` once: a digest over every artifact, the
    evaluation plan and the report flags. `prepay evaluate-lockbox` verifies the seal and the
    data-lock fingerprint, scores every model on test A/B/C, compares the selected model with the
    other baselines and M1 with B1 and B2, and writes `evaluations/first.json` once, read-only.
    A second evaluation is refused. Further experiments need a new run.
11. **Pre-declared report flags** (reported, never used to repair the model):
    `beats_baselines`, `gbm_vs_baselines`, `log_loss_degradation` (test > 1.2 × validation B),
    `prepay_calibration_degradation` (test ECE > 2 × validation B).
12. **Sampling for memory.** `--train-sample-fraction` keeps whole loans by a stable hash, never
    rows, and the fraction is recorded in the run manifest. Validation and test are always read
    in full.

## Synthetic-only diagnostic

On synthetic data, `--truth-dir` adds the mean absolute error of each model's predicted hazards
against the generator's true hazards. It checks the pipeline and is labeled as not evidence
of real accuracy.

## Not yet implemented

Feature drift (PSI), seed-repeat stability, ablations and segment reports (vintage, incentive,
term, region) are tracked in `docs/STATUS.md`.
