# ADR 0010: Forward evaluation: registered candidates, criteria and business tolerances

- Status: accepted, 2026-10-29, **before any reporting month after 2026-06 exists in this
  project**. The latest lock is Release 48, cutoff 2026-06.
- Extends ADR 0008, which stays in force. Its primary claim and its X1/X2 definitions are
  unchanged.
- Scope: the only confirmatory (E3) evidence the reliability program can produce
  (ADR 0009 §2).

## Context

The 2020-01..2026-06 windows are opened. The candidates of the reliability program were designed
after the failures there were seen, so only reporting months that nobody has seen can confirm
them. This ADR fixes, in advance:

- which sealed models compete;
- what they're compared on;
- what counts as a win;
- what level of error is acceptable for the stated use, whatever the statistics say.

## Decisions

1. **Members.** Each member is a sealed run (ADR 0004 §10). The models inside it are scored with
   their own pre-declared calibration: an ADR 0004 §7 cross-fitted temperature where adopted,
   otherwise raw.

   | Run | Training / tune / calibrate | Models |
   |---|---|---|
   | `REF`: the sealed primary run, unchanged | ≤ 2017-12 / 2018 / 2019 | M1+T (selected), B1, B2, B0 |
   | `DEV2017` | ≤ 2017-12 / 2018 / 2019 | X1, X2 (ADR 0008), X3, H1 |
   | `REFIT2026` | ≤ 2024-06 / 2024-07..2025-06 / 2025-07..2026-06 | R-M1, R-B2, R-X2, R-H1 |

   - `DEV2017` uses the primary run's training fraction and sample.
   - `REFIT2026` uses the ADR 0006 §5 memory rule, with 0.05 added as a last option. The fraction
     is recorded.
   - `REFIT2026` trains on months that are opened. That is legitimate here, because its claims
     are judged only on forward months.

   Model definitions are in code and summarized in `docs/RELIABILITY_PLAN.md` §6. X3 and H1 use
   the derived features of `prepay.features.derived` (version recorded in the manifest).

2. **Forward months.** Target months strictly after 2026-06. They come from a data lock with:
   - a release later than 48;
   - a cutoff of at least 2027-06 (12 forward months) for the **primary opening**;
   - a fingerprint differing from every member's lock.

   - **No interim looks.** No evaluation runs before the primary opening.
   - **Primary report.** The first qualifying lock produces it, written once.
   - **Monitoring reports.** Each later lock adds one, written once per lock fingerprint. They
     never replace the primary report.
   - The cohort for run-off is every eligible loan active at the end of 2026-06 in the new release.

3. **Primary family** (ADR 0008's claim), Holm-adjusted at α = 0.05. Each comparison is the paired
   multiclass log-loss difference on identical forward rows, with a loan-clustered bootstrap
   (1,000 replicates; one-sided p = share of replicates with difference ≥ 0):

   | ID | Comparison |
   |---|---|
   | P1 | X1 vs REF M1+T |
   | P2 | X2 vs REF M1+T |
   | P3 | X1 vs REF B1 |
   | P4 | X2 vs REF B1 |

4. **Secondary family**, Holm-adjusted within the family and labeled secondary:

   | ID | Comparison | Question it answers |
   |---|---|---|
   | S1 | H1 vs REF M1+T | Constrained hazard |
   | S2 | X3 vs REF M1+T | Behavioral features |
   | S3 | H1 vs REF B2 | Is the constrained hazard better than the plain logistic? |
   | S4 | R-M1 vs REF M1+T | Training window, same method (H-SUP) |
   | S5 | R-X2 vs X2 | Training window, constrained trees |
   | S6 | R-H1 vs H1 | Training window, constrained hazard |
   | S7 | R-B2 vs REF B2 | Training window, logistic |

   **Reading rule.**
   - Wins in P1–P4 but not in S4–S7 favor H-ERA.
   - Wins in S4–S7 but not in P1–P4 favor H-SUP.
   - Wins in both favor both.
   - Wins in neither weaken both hypotheses. They stay hypotheses.

   A secondary win is never re-labeled as primary.

5. **Business tolerances** (hindsight mode, for every model including REF). A model is **fit for
   the stated use in the forward regime** only if it meets T1–T3, T5 and T6, and T4 once 24
   forward months exist:

   | ID | Quantity | Tolerance |
   |---|---|---|
   | T1 | Mean monthly balance-weighted `full_payoff_only_CPR_proxy` bias over forward months | ≤ max(1.0 pp, 15% of the observed mean) |
   | T2 | 12-month cumulative payoff incidence (Aalen–Johansen), cohort at 2026-06 | \|model − realized\| ≤ max(1.0 pp, 15% of realized) |
   | T3 | Pool factor at 12 months, same cohort | \|error\| ≤ 1.0 pp |
   | T4 | Horizon-truncated WAL at 24 months | \|error\| ≤ 0.04 years |
   | T5 | ADR 0006 §7 segment cells that are not low-event | ≤ 10% poorly served (A/E interval entirely outside [0.8, 1.25]). Incentive cells < −200 and [−200, −100) are reported individually |
   | T6 | Calibration | Overall payoff A/E in [0.9, 1.1], and prepay ECE ≤ 2× the model's calibration-window ECE |

   - T2 is *not interpretable* when the censoring bounds of ADR 0006 §10 straddle the tolerance
     band.
   - As-of-rate results (flat rates known at 2026-06) are reported with the same metrics but not
     held to the tolerances, because the rate path is an input, not something the model forecasts.
   - **Scale of the tolerances.** A sustained 1 pp CPR bias moves the 12-month pool factor by about
     1 pp and the 24-month truncated WAL by about 0.02 years. So T1–T4 each allow roughly 1–2 pp of
     sustained CPR error, which is 15–30% of a 6% CPR lock-in pool.

6. **Statement of scope.** Every forward report names the regime of its months, using the
   ADR 0009 §5 bands. A verdict holds for that regime only. A forward window entirely in a
   high-rate regime says nothing about refinance-wave accuracy.

7. **Mechanism** (`prepay forward register`, `prepay forward evaluate`, ADR 0008):
   - **Registration** writes `forward-registration.json` once. It records each member's run ID,
     seal SHA-256, candidate digest and models; the families; tolerances; minimum months;
     seen-through month (2026-06); and its own digest.
   - **Evaluation** checks, in order:
     1. the registration digest and every member's seal and candidate digest;
     2. that the lock is new and its cutoff meets the minimum;
     3. that no report exists yet for that lock.

     It then reads only target months after the seen-through month and writes the report
     read-only.
   - **Tests:** a reader spy (no month ≤ 2026-06 is read), tamper refusal for the registration and
     each member, second-evaluation refusal, and refusal before the minimum months.

8. **Late candidates.** A model built after this registration can never join it. It may be
   registered separately, with its seen-through month set to the latest cutoff known on its
   registration day.

## Amendment 1 (2026-10-29, before any member run was trained)

These are definition details found while implementing `prepay.modeling.challengers`.

- **The PMMS method flag is excluded too.** Every program candidate (X1–X3, H1 and their refits)
  leaves out `pmms_application_based` as well as the two rate levels.
  - In DEV2017 the flag is constant at 0, and LightGBM can't split on a constant. So X1 and X2 are
    exactly as ADR 0008 defines them.
  - In REFIT2026 the flag would mark every month after 2022-11 and act as an era dummy, which the
    program removes on purpose.
  - R-M1 keeps the flag, because it is the primary method refit unchanged.
- **H1 also leaves out nominal loan size and remaining payments.** Loan size drifts with era
  (RELIABILITY_PLAN A2). Remaining payments add nothing beyond age for the terms in scope.
- **The DEV2017 designated model is X2.** Experiment runs never select; the seal needs one
  designated model, and it has no other role.

## Consequences

The first confirmatory evidence arrives around Release 52, in late 2027. Until then the product
must present the primary model as **not validated across regimes**, and present projections with
the ADR 0009 §7 verdict. If no model is fit for use in the forward regime, the system says so;
it doesn't fall back to a different model without a label.
