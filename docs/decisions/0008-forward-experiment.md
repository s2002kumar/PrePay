# ADR 0008: Follow-up experiment on a rate-regime-robust payoff model, judged only on future months

- Status: **proposed**. Running it needs later Freddie Mac releases and the owner's decision.
- Date: 2026-10-29, written after the single real-data lockbox opening (ADR 0006).
- Scope: a separate research experiment. The sealed primary run, its report and its selection stay
  unchanged.

## Context

The primary real-data run has been sealed and evaluated once on 2020-01 to 2026-06. Its results,
including failed checks, are in the private review packet (ADR 0006 §3). Two lessons can be stated
without real-data figures:

1. **Rate level is confounded with era in the training span.** In the public PMMS history for
   1999–2017, the 30-year rate was above about 5.5% only before 2009. So in the training data,
   "in the money while rates are high" happens almost entirely in the 2001–2003 refinance waves. A
   model that uses the absolute rate level (`market_rate_t1`, `note_rate_pct`) can learn that era's
   behaviour as a function of the level. When rates are high again in a later era, that learned
   behaviour may not apply.
2. **The opened windows can no longer judge a revision fairly.** Anything designed after reading
   the 2020–2026 results would be fitted, implicitly, to them.

## Decision (pre-registered now, before any such model is trained)

**Candidates.** Same features, panel and training window (≤ 2017-12) as the primary run.

| ID | Model |
|---|---|
| X1 | LightGBM without `market_rate_t1` and `note_rate_pct`; incentive, rate change and SATO kept. Payoff probability non-decreasing in `incentive_bps`. |
| X2 | X1, plus payoff probability non-increasing in `burnout_months`. |
| Ref | The sealed primary run's models (B1, B2, M1+T), unchanged. |

**Structure.** LightGBM's multiclass objective applies a monotone constraint to every class score,
so it does not guarantee a monotone payoff probability after the softmax (checked with LightGBM
4.7.0). X1 and X2 therefore use two binary models:
- a credit hazard `c(x)`, unconstrained;
- a payoff hazard `h(x)` fitted on rows without a credit exit, with the monotone constraints.

They combine as `p_C = c`, `p_P = (1 − c)·h`, `p_active = (1 − c)(1 − h)`, which is coherent by
construction. Monotonicity of `p_P` in incentive then holds wherever `c` does not rise with
incentive. This is checked on the Validation B grid and reported.

**Tuning.**
- Validation A (2018) for the same grids as ADR 0004.
- Validation B (2019) for cross-fitted temperature.
- The training fraction is the same as the primary run's.
- No 2020–2026 data is used for any choice.

**Evaluation.** One opening, on **forward months**: reporting periods strictly after 2026-06,
taken from a later release, once at least 12 such months exist.
- All candidates and the sealed reference run are scored on the same months with the ADR 0006
  metrics: log loss with paired loan-clustered intervals, calibration, segments, cohort run-off
  from t0 = 2026-06.
- The primary claim is X1 or X2 against the sealed M1+T and against B1. The sealed run's forward
  scores are reported whatever they show.

**Mechanism to build first:** `prepay forward-evaluate`.
- It requires a sealed run and a new data lock whose cutoff is later than the run's.
- It reads only months after the run's lock cutoff.
- It writes a write-once report per (run, lock fingerprint).
- Its tests mirror the lockbox tests: holdout spy, tamper refusal, second-evaluation refusal.

## Consequences

- The primary result stays the primary result.
- If X1 or X2 wins on forward months, that is evidence about the confound hypothesis from data
  nobody has seen. If not, the hypothesis is weakened and stays a hypothesis.
- Until enough forward months exist, nothing here is run. The cost is time, not compute: each
  quarterly release adds about three months.
