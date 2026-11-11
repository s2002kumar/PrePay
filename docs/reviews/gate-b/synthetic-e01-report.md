# E01 local report

**Synthetic data.** Every number here comes from a fictional dataset. It shows the report's format and the pipeline working, nothing about real mortgages.

> Development evidence (E1), exploratory. Outcome months up to 2019-12 only. Not confirmation of performance on 2020-2026 or on any future month (ADR 0014).

## Status

- Folds finished: 6 of 6 (2007-12, 2009-12, 2011-12, 2013-12, 2015-12, 2017-12).
- Stability S1 finished: samples.
- Complete: no; rule results may be incomplete.
- Pilot byte identity against the V1 run: identical.

## What the reading rules found

**R7.** No family is nominated: no development evidence for a change.

**R2 vs M1** (consistency, not proof):

- B2 does not show a consistent advantage over M1 (1 of 4 regime-shift folds with lower loss).
- X1 does not show a consistent advantage over M1 (2 of 4 regime-shift folds with lower loss).
- X2 does not show a consistent advantage over M1 (1 of 4 regime-shift folds with lower loss).
- X3 does not show a consistent advantage over M1 (0 of 4 regime-shift folds with lower loss).
- H1 does not show a consistent advantage over M1 (1 of 4 regime-shift folds with lower loss).

**R2 vs B2** (consistency, not proof):

- M1 does not show a consistent advantage over B2 (2 of 4 regime-shift folds with lower loss).
- X1 does not show a consistent advantage over B2 (2 of 4 regime-shift folds with lower loss).
- X2 has lower loss than B2 in 3 of 4 of the regime-shift folds, but a loss in a control fold is not ruled out.
- X3 has lower loss than B2 in 3 of 4 of the regime-shift folds, but a loss in a control fold is not ruled out.
- H1 does not show a consistent advantage over B2 (2 of 4 regime-shift folds with lower loss).

**R3** (bundled design choices; no single cause attributed):

- X1 - M1: no consistent difference across the regime-shift folds. Differs in: factored two-booster structure vs joint softmax; market_rate_t1, note_rate_pct and pmms_application_based removed from both boosters; payoff hazard non-decreasing in incentive.
- X2 - X1: no consistent difference across the regime-shift folds. Differs in: only the burnout constraint (payoff hazard non-increasing in burnout); each model is still tuned on its own. This pair is the closest to a single change.
- X3 - X2: no consistent difference across the regime-shift folds. Differs in: three derived behavioral features (new opportunity, new five-year low, payment saving %), each constrained non-decreasing.
- H1 - X2: no consistent difference across the regime-shift folds. Differs in: penalized logistic with piecewise-linear terms vs trees; logit-linear vs flat tails; H1 drops loan size and remaining payments, adds new opportunity, hinge and seasonal terms; different credit model.
- H1 - B2: no consistent difference across the regime-shift folds. Differs in: factored vs joint form; monotone constraints; no rate levels or loan size; different bases and features.

**R4** (calibration transfer, a diagnostic): transfers for no family; doesn't for B0 (31 cells), B1 (22 cells), B2 (21 cells), H1 (21 cells), M1 (20 cells), X1 (21 cells), X2 (19 cells), X3 (21 cells).

**R5** (run-off errors beyond the T3/T4 tolerances, hindsight rates): 2007-12 B0 T3, 2007-12 B0 T4, 2007-12 B1 T3, 2007-12 B1 T4, 2007-12 B2 T3, 2007-12 B2 T4, 2007-12 H1 T3, 2007-12 H1 T4, 2007-12 M1 T3, 2007-12 M1 T4, 2007-12 X1 T3, 2007-12 X1 T4, 2007-12 X2 T3, 2007-12 X2 T4, 2007-12 X3 T3, 2007-12 X3 T4, 2009-12 B0 T3, 2009-12 B0 T4, 2009-12 B1 T3, 2009-12 B1 T4, 2009-12 B2 T3, 2009-12 B2 T4, 2009-12 H1 T3, 2009-12 H1 T4, 2011-12 B0 T3, 2011-12 B0 T4, 2011-12 B1 T3, 2011-12 B1 T4, 2011-12 B2 T3, 2011-12 M1 T3, 2011-12 M1 T4, 2011-12 X1 T3, 2011-12 X1 T4, 2011-12 X2 T3, 2011-12 X2 T4, 2011-12 X3 T3, 2011-12 X3 T4, 2013-12 B2 T3, 2013-12 H1 T3, 2013-12 M1 T3, 2013-12 X2 T3, 2015-12 B0 T3, 2015-12 B0 T4, 2017-12 B0 T3, 2017-12 B0 T4.

**R6** (robustness diagnostic): SD of tune-window log loss across loan samples: B2 4.93e-05, M1 2.96e-04, X2 1.22e-04, H1 9.62e-05; across seeds: B0 0.00e+00, B1 0.00e+00, B2 0.00e+00, H1 0.00e+00.

## Comparisons

Difference = candidate minus reference mean log loss (nats per loan-month); negative means lower loss. Relative = difference / reference. Intervals: simultaneous within each family (Bonferroni).

### F-M1

| Fold | Class of fold | Pair | Difference | Relative | Simultaneous 95% | Class | Sampling |
|---|---|---|---|---|---|---|---|
| 2007-12 | regime shift | B2 - M1 | -4.14e-03 | -4.47% | [-5.85e-03, -2.43e-03] | lower loss | not fragile |
| 2007-12 | regime shift | X1 - M1 | -3.11e-04 | -0.34% | [-5.60e-04, -6.19e-05] | lower loss | not assessable |
| 2007-12 | regime shift | X2 - M1 | -3.11e-04 | -0.34% | [-5.60e-04, -6.19e-05] | lower loss | not fragile |
| 2007-12 | regime shift | X3 - M1 | -2.34e-04 | -0.25% | [-4.89e-04, +2.09e-05] | non inferior | not assessable |
| 2007-12 | regime shift | H1 - M1 | -5.36e-03 | -5.78% | [-7.82e-03, -2.90e-03] | lower loss | not fragile |
| 2009-12 | regime shift | B2 - M1 | +9.33e-03 | +9.26% | [+4.59e-03, +1.41e-02] | higher loss | not fragile |
| 2009-12 | regime shift | X1 - M1 | -7.76e-04 | -0.77% | [-1.40e-03, -1.56e-04] | lower loss | not assessable |
| 2009-12 | regime shift | X2 - M1 | -6.43e-04 | -0.64% | [-1.30e-03, +1.03e-05] | non inferior | not fragile |
| 2009-12 | regime shift | X3 - M1 | -5.71e-04 | -0.57% | [-1.41e-03, +2.65e-04] | non inferior | not assessable |
| 2009-12 | regime shift | H1 - M1 | +9.77e-02 | +96.99% | [+5.80e-02, +1.37e-01] | higher loss | not fragile |
| 2011-12 | regime shift | B2 - M1 | +1.55e-03 | +2.64% | [+4.19e-04, +2.69e-03] | higher loss | not fragile |
| 2011-12 | regime shift | X1 - M1 | +2.86e-04 | +0.49% | [-1.12e-04, +6.84e-04] | inconclusive | not assessable |
| 2011-12 | regime shift | X2 - M1 | +2.03e-04 | +0.35% | [-1.91e-04, +5.97e-04] | inconclusive | fragile |
| 2011-12 | regime shift | X3 - M1 | +5.89e-05 | +0.10% | [-3.83e-04, +5.00e-04] | inconclusive | not assessable |
| 2011-12 | regime shift | H1 - M1 | -4.12e-05 | -0.07% | [-9.09e-04, +8.27e-04] | inconclusive | fragile |
| 2013-12 | regime shift | B2 - M1 | +5.96e-04 | +1.24% | [-1.31e-05, +1.21e-03] | inconclusive | not fragile |
| 2013-12 | regime shift | X1 - M1 | -2.87e-05 | -0.06% | [-2.14e-04, +1.56e-04] | non inferior | not assessable |
| 2013-12 | regime shift | X2 - M1 | -9.45e-05 | -0.20% | [-2.78e-04, +8.93e-05] | non inferior | fragile |
| 2013-12 | regime shift | X3 - M1 | -1.10e-04 | -0.23% | [-3.52e-04, +1.32e-04] | non inferior | not assessable |
| 2013-12 | regime shift | H1 - M1 | +9.76e-04 | +2.03% | [+3.30e-04, +1.62e-03] | higher loss | not fragile |
| 2015-12 | control | B2 - M1 | -9.66e-05 | -0.19% | [-5.04e-04, +3.11e-04] | inconclusive | fragile |
| 2015-12 | control | X1 - M1 | +1.28e-06 | +0.00% | [-1.90e-04, +1.92e-04] | non inferior | not assessable |
| 2015-12 | control | X2 - M1 | -1.40e-05 | -0.03% | [-1.89e-04, +1.61e-04] | non inferior | fragile |
| 2015-12 | control | X3 - M1 | +2.00e-05 | +0.04% | [-1.88e-04, +2.28e-04] | non inferior | not assessable |
| 2015-12 | control | H1 - M1 | +1.42e-03 | +2.82% | [+5.85e-04, +2.26e-03] | higher loss | not fragile |
| 2017-12 | control | B2 - M1 | -3.64e-04 | -1.08% | [-7.42e-04, +1.37e-05] | non inferior | not fragile |
| 2017-12 | control | X1 - M1 | +3.01e-06 | +0.01% | [-1.27e-04, +1.33e-04] | non inferior | not assessable |
| 2017-12 | control | X2 - M1 | -8.04e-05 | -0.24% | [-2.10e-04, +4.92e-05] | non inferior | fragile |
| 2017-12 | control | X3 - M1 | -8.23e-05 | -0.24% | [-2.36e-04, +7.12e-05] | non inferior | not assessable |
| 2017-12 | control | H1 - M1 | +2.31e-05 | +0.07% | [-4.02e-04, +4.48e-04] | inconclusive | fragile |

### F-B2

| Fold | Class of fold | Pair | Difference | Relative | Simultaneous 95% | Class | Sampling |
|---|---|---|---|---|---|---|---|
| 2007-12 | regime shift | M1 - B2 | +4.14e-03 | +4.68% | [+2.43e-03, +5.85e-03] | higher loss | not fragile |
| 2007-12 | regime shift | X1 - B2 | +3.83e-03 | +4.33% | [+2.16e-03, +5.50e-03] | higher loss | not assessable |
| 2007-12 | regime shift | X2 - B2 | +3.83e-03 | +4.33% | [+2.16e-03, +5.50e-03] | higher loss | not fragile |
| 2007-12 | regime shift | X3 - B2 | +3.91e-03 | +4.41% | [+2.23e-03, +5.58e-03] | higher loss | not assessable |
| 2007-12 | regime shift | H1 - B2 | -1.22e-03 | -1.37% | [-2.30e-03, -1.32e-04] | lower loss | not fragile |
| 2009-12 | regime shift | M1 - B2 | -9.33e-03 | -8.48% | [-1.41e-02, -4.59e-03] | lower loss | not fragile |
| 2009-12 | regime shift | X1 - B2 | -1.01e-02 | -9.18% | [-1.47e-02, -5.53e-03] | lower loss | not assessable |
| 2009-12 | regime shift | X2 - B2 | -9.97e-03 | -9.06% | [-1.46e-02, -5.38e-03] | lower loss | not fragile |
| 2009-12 | regime shift | X3 - B2 | -9.90e-03 | -9.00% | [-1.46e-02, -5.24e-03] | lower loss | not assessable |
| 2009-12 | regime shift | H1 - B2 | +8.84e-02 | +80.29% | [+5.28e-02, +1.24e-01] | higher loss | not fragile |
| 2011-12 | regime shift | M1 - B2 | -1.55e-03 | -2.57% | [-2.69e-03, -4.19e-04] | lower loss | not fragile |
| 2011-12 | regime shift | X1 - B2 | -1.27e-03 | -2.10% | [-2.36e-03, -1.74e-04] | lower loss | not assessable |
| 2011-12 | regime shift | X2 - B2 | -1.35e-03 | -2.24% | [-2.41e-03, -2.86e-04] | lower loss | not fragile |
| 2011-12 | regime shift | X3 - B2 | -1.49e-03 | -2.48% | [-2.53e-03, -4.56e-04] | lower loss | not assessable |
| 2011-12 | regime shift | H1 - B2 | -1.59e-03 | -2.64% | [-2.26e-03, -9.24e-04] | lower loss | not fragile |
| 2013-12 | regime shift | M1 - B2 | -5.96e-04 | -1.23% | [-1.21e-03, +1.31e-05] | non inferior | not fragile |
| 2013-12 | regime shift | X1 - B2 | -6.25e-04 | -1.28% | [-1.26e-03, +1.49e-05] | non inferior | not assessable |
| 2013-12 | regime shift | X2 - B2 | -6.91e-04 | -1.42% | [-1.30e-03, -7.83e-05] | lower loss | not fragile |
| 2013-12 | regime shift | X3 - B2 | -7.06e-04 | -1.45% | [-1.39e-03, -2.65e-05] | lower loss | not assessable |
| 2013-12 | regime shift | H1 - B2 | +3.79e-04 | +0.78% | [+1.15e-04, +6.43e-04] | higher loss | not fragile |
| 2015-12 | control | M1 - B2 | +9.66e-05 | +0.19% | [-3.11e-04, +5.04e-04] | inconclusive | fragile |
| 2015-12 | control | X1 - B2 | +9.79e-05 | +0.19% | [-3.16e-04, +5.12e-04] | inconclusive | not assessable |
| 2015-12 | control | X2 - B2 | +8.26e-05 | +0.16% | [-3.38e-04, +5.03e-04] | inconclusive | fragile |
| 2015-12 | control | X3 - B2 | +1.17e-04 | +0.23% | [-2.73e-04, +5.06e-04] | inconclusive | not assessable |
| 2015-12 | control | H1 - B2 | +1.52e-03 | +3.01% | [+7.40e-04, +2.30e-03] | higher loss | not fragile |
| 2017-12 | control | M1 - B2 | +3.64e-04 | +1.09% | [-1.37e-05, +7.42e-04] | inconclusive | not fragile |
| 2017-12 | control | X1 - B2 | +3.67e-04 | +1.10% | [-2.67e-05, +7.61e-04] | inconclusive | not assessable |
| 2017-12 | control | X2 - B2 | +2.84e-04 | +0.85% | [-8.51e-05, +6.53e-04] | inconclusive | not fragile |
| 2017-12 | control | X3 - B2 | +2.82e-04 | +0.85% | [-8.69e-05, +6.51e-04] | inconclusive | not assessable |
| 2017-12 | control | H1 - B2 | +3.87e-04 | +1.16% | [+1.37e-04, +6.37e-04] | higher loss | not fragile |

### F-DESIGN

| Fold | Class of fold | Pair | Difference | Relative | Simultaneous 95% | Class | Sampling |
|---|---|---|---|---|---|---|---|
| 2007-12 | regime shift | X1 - M1 | -3.11e-04 | -0.34% | [-5.60e-04, -6.19e-05] | lower loss | not assessable |
| 2007-12 | regime shift | X2 - X1 | +0.00e+00 | +0.00% | [+0.00e+00, +0.00e+00] | non inferior | not assessable |
| 2007-12 | regime shift | X3 - X2 | +7.65e-05 | +0.08% | [-3.51e-05, +1.88e-04] | non inferior | not assessable |
| 2007-12 | regime shift | H1 - X2 | -5.05e-03 | -5.47% | [-7.46e-03, -2.63e-03] | lower loss | not fragile |
| 2007-12 | regime shift | H1 - B2 | -1.22e-03 | -1.37% | [-2.30e-03, -1.32e-04] | lower loss | not fragile |
| 2009-12 | regime shift | X1 - M1 | -7.76e-04 | -0.77% | [-1.40e-03, -1.56e-04] | lower loss | not assessable |
| 2009-12 | regime shift | X2 - X1 | +1.32e-04 | +0.13% | [-8.49e-05, +3.50e-04] | non inferior | not assessable |
| 2009-12 | regime shift | X3 - X2 | +7.23e-05 | +0.07% | [-6.04e-04, +7.48e-04] | inconclusive | not assessable |
| 2009-12 | regime shift | H1 - X2 | +9.83e-02 | +98.25% | [+5.88e-02, +1.38e-01] | higher loss | not fragile |
| 2009-12 | regime shift | H1 - B2 | +8.84e-02 | +80.29% | [+5.28e-02, +1.24e-01] | higher loss | not fragile |
| 2011-12 | regime shift | X1 - M1 | +2.86e-04 | +0.49% | [-1.12e-04, +6.84e-04] | inconclusive | not assessable |
| 2011-12 | regime shift | X2 - X1 | -8.27e-05 | -0.14% | [-2.53e-04, +8.81e-05] | non inferior | not assessable |
| 2011-12 | regime shift | X3 - X2 | -1.44e-04 | -0.24% | [-4.48e-04, +1.59e-04] | non inferior | not assessable |
| 2011-12 | regime shift | H1 - X2 | -2.44e-04 | -0.41% | [-1.02e-03, +5.34e-04] | inconclusive | not fragile |
| 2011-12 | regime shift | H1 - B2 | -1.59e-03 | -2.64% | [-2.26e-03, -9.24e-04] | lower loss | not fragile |
| 2013-12 | regime shift | X1 - M1 | -2.87e-05 | -0.06% | [-2.14e-04, +1.56e-04] | non inferior | not assessable |
| 2013-12 | regime shift | X2 - X1 | -6.58e-05 | -0.14% | [-2.08e-04, +7.67e-05] | non inferior | not assessable |
| 2013-12 | regime shift | X3 - X2 | -1.52e-05 | -0.03% | [-1.93e-04, +1.62e-04] | non inferior | not assessable |
| 2013-12 | regime shift | H1 - X2 | +1.07e-03 | +2.23% | [+4.16e-04, +1.72e-03] | higher loss | not fragile |
| 2013-12 | regime shift | H1 - B2 | +3.79e-04 | +0.78% | [+1.15e-04, +6.43e-04] | higher loss | not fragile |
| 2015-12 | control | X1 - M1 | +1.28e-06 | +0.00% | [-1.90e-04, +1.92e-04] | non inferior | not assessable |
| 2015-12 | control | X2 - X1 | -1.53e-05 | -0.03% | [-1.52e-04, +1.22e-04] | non inferior | not assessable |
| 2015-12 | control | X3 - X2 | +3.40e-05 | +0.07% | [-1.43e-04, +2.11e-04] | non inferior | not assessable |
| 2015-12 | control | H1 - X2 | +1.44e-03 | +2.85% | [+6.22e-04, +2.25e-03] | higher loss | not fragile |
| 2015-12 | control | H1 - B2 | +1.52e-03 | +3.01% | [+7.40e-04, +2.30e-03] | higher loss | not fragile |
| 2017-12 | control | X1 - M1 | +3.01e-06 | +0.01% | [-1.27e-04, +1.33e-04] | non inferior | not assessable |
| 2017-12 | control | X2 - X1 | -8.35e-05 | -0.25% | [-1.59e-04, -7.72e-06] | lower loss | not assessable |
| 2017-12 | control | X3 - X2 | -1.86e-06 | -0.01% | [-1.44e-04, +1.40e-04] | non inferior | not assessable |
| 2017-12 | control | H1 - X2 | +1.04e-04 | +0.31% | [-3.26e-04, +5.33e-04] | inconclusive | fragile |
| 2017-12 | control | H1 - B2 | +3.87e-04 | +1.16% | [+1.37e-04, +6.37e-04] | higher loss | not fragile |

## Folds

### 2007-12 (regime shift, 2008-01..2009-12)

Support of the evaluation window (by balance): unsupported; outside 95.5%, thin 4.5%.

| Model | Log loss | Brier | Payoff A/E | CPR bias, pp | CPR MAE, pp |
|---|---|---|---|---|---|
| B0 | 0.09050 | 0.03221 | 2.377 [2.153, 2.620] | -10.67 [-11.95, -9.34] | 10.67 |
| B1 | 0.09339 | 0.03229 | 2.755 [2.486, 3.038] | -11.51 [-12.80, -10.17] | 11.51 |
| B2 | 0.08847 | 0.03215 | 1.836 [1.698, 1.988] | -8.50 [-9.51, -7.45] | 8.50 |
| M1 | 0.09261 | 0.03228 | 2.728 [2.463, 3.010] | -11.46 [-12.76, -10.11] | 11.46 |
| X1 | 0.09230 | 0.03226 | 2.684 [2.430, 2.958] | -11.31 [-12.59, -9.98] | 11.31 |
| X2 | 0.09230 | 0.03226 | 2.684 [2.430, 2.958] | -11.31 [-12.59, -9.98] | 11.31 |
| X3 | 0.09238 | 0.03227 | 2.680 [2.427, 2.954] | -11.34 [-12.62, -10.01] | 11.34 |
| H1 | 0.08725 | 0.03209 | 1.275 [1.160, 1.426] | -4.79 [-5.81, -3.70] | 4.79 |

### 2009-12 (regime shift, 2010-01..2011-12)

Support of the evaluation window (by balance): unsupported; outside 100.0%, thin 0.0%.

| Model | Log loss | Brier | Payoff A/E | CPR bias, pp | CPR MAE, pp |
|---|---|---|---|---|---|
| B0 | 0.09925 | 0.03876 | 1.176 [1.082, 1.280] | -3.99 [-5.49, -2.56] | 4.23 |
| B1 | 0.10169 | 0.03896 | 1.091 [1.008, 1.182] | -2.24 [-3.71, -0.80] | 3.25 |
| B2 | 0.11005 | 0.04152 | 0.507 [0.450, 0.581] | +14.18 [+11.47, +16.99] | 14.18 |
| M1 | 0.10072 | 0.03889 | 0.923 [0.860, 0.992] | +0.63 [-0.53, +1.95] | 2.35 |
| X1 | 0.09994 | 0.03886 | 0.924 [0.855, 0.991] | +0.88 [-0.43, +2.27] | 2.65 |
| X2 | 0.10008 | 0.03887 | 0.922 [0.850, 0.992] | +0.84 [-0.53, +2.28] | 2.69 |
| X3 | 0.10015 | 0.03884 | 0.881 [0.807, 0.957] | +2.12 [+0.64, +3.59] | 3.52 |
| H1 | 0.19841 | 0.10397 | 0.177 [0.148, 0.218] | +47.52 [+41.55, +53.21] | 47.52 |

### 2011-12 (regime shift, 2012-01..2013-12)

Support of the evaluation window (by balance): unsupported; outside 94.7%, thin 5.3%.

| Model | Log loss | Brier | Payoff A/E | CPR bias, pp | CPR MAE, pp |
|---|---|---|---|---|---|
| B0 | 0.06208 | 0.02130 | 0.746 [0.627, 0.863] | +3.08 [+1.51, +4.88] | 4.10 |
| B1 | 0.05988 | 0.02129 | 0.751 [0.664, 0.837] | +3.14 [+2.18, +4.10] | 3.37 |
| B2 | 0.06036 | 0.02132 | 1.022 [0.911, 1.157] | -0.75 [-1.91, +0.36] | 2.62 |
| M1 | 0.05881 | 0.02125 | 0.754 [0.684, 0.829] | +2.89 [+2.11, +3.65] | 3.03 |
| X1 | 0.05909 | 0.02129 | 0.740 [0.669, 0.817] | +3.03 [+2.10, +3.91] | 3.23 |
| X2 | 0.05901 | 0.02127 | 0.747 [0.674, 0.827] | +2.92 [+1.99, +3.80] | 3.14 |
| X3 | 0.05887 | 0.02125 | 0.771 [0.701, 0.844] | +2.59 [+1.78, +3.44] | 2.80 |
| H1 | 0.05877 | 0.02124 | 1.006 [0.903, 1.136] | -1.00 [-2.08, +0.09] | 2.50 |

### 2013-12 (regime shift, 2014-01..2015-12)

Support of the evaluation window (by balance): extrapolating; outside 21.6%, thin 74.6%.

| Model | Log loss | Brier | Payoff A/E | CPR bias, pp | CPR MAE, pp |
|---|---|---|---|---|---|
| B0 | 0.04935 | 0.01644 | 1.218 [1.103, 1.347] | -2.17 [-3.11, -1.29] | 2.53 |
| B1 | 0.04882 | 0.01645 | 1.073 [0.982, 1.173] | -1.40 [-2.07, -0.71] | 1.77 |
| B2 | 0.04863 | 0.01644 | 0.906 [0.828, 0.995] | +0.77 [+0.10, +1.38] | 1.56 |
| M1 | 0.04804 | 0.01643 | 0.930 [0.843, 1.029] | -0.14 [-0.95, +0.62] | 1.66 |
| X1 | 0.04801 | 0.01643 | 0.956 [0.866, 1.056] | -0.48 [-1.26, +0.27] | 1.52 |
| X2 | 0.04794 | 0.01642 | 0.926 [0.838, 1.028] | -0.12 [-0.97, +0.68] | 1.69 |
| X3 | 0.04793 | 0.01642 | 1.012 [0.919, 1.110] | -0.99 [-1.71, -0.26] | 1.55 |
| H1 | 0.04901 | 0.01645 | 0.884 [0.811, 0.967] | +0.61 [-0.13, +1.25] | 1.57 |

### 2015-12 (control, 2016-01..2017-12)

Support of the evaluation window (by balance): extrapolating; outside 16.8%, thin 83.2%.

| Model | Log loss | Brier | Payoff A/E | CPR bias, pp | CPR MAE, pp |
|---|---|---|---|---|---|
| B0 | 0.05233 | 0.01776 | 1.123 [0.937, 1.337] | -1.46 [-3.38, +0.29] | 3.58 |
| B1 | 0.05132 | 0.01775 | 0.924 [0.826, 1.037] | +0.34 [-0.78, +1.32] | 2.15 |
| B2 | 0.05044 | 0.01771 | 0.984 [0.910, 1.067] | +0.09 [-0.44, +0.67] | 1.17 |
| M1 | 0.05053 | 0.01772 | 1.040 [0.948, 1.139] | -0.72 [-1.54, +0.05] | 1.62 |
| X1 | 0.05053 | 0.01772 | 0.996 [0.910, 1.092] | -0.36 [-1.15, +0.32] | 1.50 |
| X2 | 0.05052 | 0.01772 | 1.023 [0.933, 1.115] | -0.63 [-1.44, +0.11] | 1.53 |
| X3 | 0.05055 | 0.01772 | 1.010 [0.930, 1.097] | -0.46 [-1.13, +0.19] | 1.43 |
| H1 | 0.05196 | 0.01773 | 1.007 [0.929, 1.090] | -0.28 [-0.79, +0.27] | 1.17 |

### 2017-12 (control, 2018-01..2019-12)

Support of the evaluation window (by balance): unsupported; outside 42.3%, thin 57.7%.

| Model | Log loss | Brier | Payoff A/E | CPR bias, pp | CPR MAE, pp |
|---|---|---|---|---|---|
| B0 | 0.03527 | 0.01082 | 0.955 [0.742, 1.193] | -0.07 [-1.58, +1.31] | 3.03 |
| B1 | 0.03438 | 0.01081 | 0.970 [0.841, 1.094] | -0.29 [-1.05, +0.44] | 1.61 |
| B2 | 0.03327 | 0.01078 | 1.015 [0.929, 1.099] | -0.26 [-0.60, +0.04] | 0.70 |
| M1 | 0.03363 | 0.01079 | 0.934 [0.816, 1.039] | -0.04 [-0.68, +0.58] | 1.32 |
| X1 | 0.03364 | 0.01079 | 0.919 [0.796, 1.027] | +0.08 [-0.60, +0.71] | 1.42 |
| X2 | 0.03355 | 0.01079 | 0.912 [0.802, 1.014] | +0.09 [-0.52, +0.66] | 1.28 |
| X3 | 0.03355 | 0.01079 | 0.969 [0.859, 1.068] | -0.26 [-0.85, +0.31] | 1.20 |
| H1 | 0.03366 | 0.01079 | 1.084 [0.994, 1.172] | -0.78 [-1.15, -0.45] | 0.94 |

## Caveats

- Development evidence only (outcome months up to 2019-12). Nothing here shows how any model performed or would perform on 2020-2026 or on future months.
- The regime classes are analogues. All four regime-shift folds are low-rate shifts; no fold has rates above its training range, so lock-in (2022+) is only weakly tested.
- Folds overlap and are serially dependent. Fold counts describe consistency; no test is pooled across folds.
- Classes come from Bonferroni-simultaneous intervals within each declared family. 'Inconclusive' is not evidence of equivalence or of non-inferiority.
- Compared pairs differ in bundles of design choices. Only X2 - X1 isolates one choice. No difference is attributed to a single cause.
- Stability (R6) is a robustness diagnostic, not a test or a gate.
- The run-off 'curtailment' line is a recast-convention residual and overstates curtailments for no-recast loans (R2 defect 1).
- A nomination (R7) is a recommendation only. Confirmation can come only from a separate forward registration judged on months after its own registration.
