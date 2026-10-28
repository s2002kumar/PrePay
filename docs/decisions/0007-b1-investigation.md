# ADR 0007: Why B1 lost, and no revised model in this study

- Status: accepted, 2026-10-28, before any real-data model was trained
- Scope: diagnosis requested for the small synthetic world (VALIDATION_REPORT §5.1). Its report is
  unchanged.

## Question

In the small synthetic world the parsimony rule selected B1 (age × incentive lookup). In the sealed
holdout B1 then lost to B2 on every window, and it overstated payoffs for deeply out-of-the-money
loans: 24-month payoff incidence of 0.17 vs a realized 0.05 for the 2021-12 cohort.

## Method

The world was rebuilt from the same seed into a scratch area. Training is deterministic, so the
retrained run reproduced the original validation log losses exactly (B1 0.02687, B2 0.02625,
M1 0.02640) and the same selection. `prepay diagnose-incentive` then reads only training and
Validation B rows:

- **Bin support:** training rows and payoffs in each B1 incentive bin.
- **Partial dependence:** the mean predicted monthly payoff hazard when every Validation B
  reference row is re-scored at each incentive from −400 to +300 bp, for B1, B2 and M1.
- **Truth curve:** the same curve for the generator's true hazard, over the same rows.

## Findings (synthetic)

| Incentive (bp) | True CPR | B1 | B2 | M1 |
|---:|---:|---:|---:|---:|
| −400 | 1.3% | 7.5% | 1.9% | 7.3% |
| −200 | 2.5% | 7.5% | 4.1% | 7.3% |
| −100 | 3.6% | 6.0% | 5.8% | 7.3% |
| 0 | 5.6% | 8.2% | 6.1% | 8.1% |
| +100 | 26.2% | 21.6% | 20.4% | 22.0% |
| +200 | 43.3% | 19.9% | 30.2% | 26.7% |

1. **No training support below about −150 bp.** B1's lowest bin (incentive < −100 bp) had 4,024
   training rows and 14 payoffs, and 90% of its rows lay between −154 and −101 bp. Rates mostly
   fell in the training years, so deeply out-of-the-money loans barely occur before 2018. Every
   model predicts the 2022+ lock-in regime by extrapolation.
2. **B1 extrapolates flat and too high.**
   - One bin covers everything below −100 bp.
   - Each age × incentive cell is shrunk toward the *global* class frequencies (a Dirichlet prior
     worth 200 rows), about 12% CPR. A sparse cell is pulled up toward that average.
   - So B1 predicts 7.5% CPR at −400 bp, more than its own [−100, 0) bin (6.0%), while the truth
     falls to 1.3%.
3. **B1's refinance curve is too flat.** Bins at 50 bp steps, no burnout and no seasonality cap it
   near 20–23% CPR, against the truth's 43%.
4. **LightGBM shares the flat tail** (7.3% at −400 bp). Trees extrapolate as constants beyond the
   data.
5. **B2 has the right shape, partly by construction.** Its linear spline tail falls with incentive
   like the truth (1.9% at −400 bp), but it shares the generator's logit form.
6. **Selection:** with 79 validation payoffs the rule couldn't separate B1 from B2 and kept the
   simpler model. In the 8× world (§5.2) it could, and picked B2. The rule itself wasn't the
   defect; the evidence was too small for it.

## Decision

- **No revised B1 or selection rule in this study.** Every model, not only B1, extrapolates into
  the lock-in regime. A model built to extrapolate better has to be judged on deeply
  out-of-the-money data it has never seen. In the real data, the only such period is the sealed
  2022–2026 holdout, so a revision designed after the primary opening couldn't be tested on it
  fairly.
- **The real study still measures the failure directly.** ADR 0006 §7 pre-registered the
  incentive segments <−200 and [−200, −100) for every model on every test window. The same
  diagnosis is run on real training and validation data before sealing (private packet).
- **Future experiment, if wanted.** A lookup or GBM with an economically constrained tail (payoff
  hazard non-increasing as incentive falls), declared in its own ADR. It would be evaluated on
  reporting months after 2026-06 from a later Freddie Mac release, which no current model has
  seen.

## Consequences

The small-world report keeps its wording: the selected B1 lost, as written. Reviewers get a
mechanism, not just an outcome. The real-data selection runs under ADR 0004 unchanged.
