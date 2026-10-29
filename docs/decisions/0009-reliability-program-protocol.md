# ADR 0009: Reliability program protocol: evidence classes, rolling-origin development, private execution

- Status: accepted, 2026-10-29. Written after the single real-data lockbox opening and before any
  experiment of the program ran on real data.
- Scope: the program in `docs/RELIABILITY_PLAN.md`. ADR 0002–0008 stay in force for the primary
  run.

## Context

The sealed primary run failed pre-registered checks across rate regimes (private packet; the
owner's brief describes it without figures). The owner asked for a diagnosis and better models
without disturbing the original study. Two constraints shape everything here:

- Every idea in the program was formed **after** the 2020-01..2026-06 outcomes were seen.
- The owner's brief of 2026-10-29 says that private Freddie Mac data, restricted artifacts and
  **derived outputs** must not be sent to hosted AI services until data-use permission is
  clarified. The implementing agent is such a service.

## Decisions

1. **Frozen.** The primary run directory, its seal, `evaluations/first.json`, the data lock of
   Release 48 and the private packet are never modified, re-scored to revise a claim, or replaced.
   New work creates new run directories with new IDs.

2. **Evidence classes.** Every experiment manifest and report carries `evidence_class`:
   - `synthetic` (E0);
   - `development` (E1): real outcome months ≤ 2019-12;
   - `exploratory-opened-window` (E2): any real month in 2020-01..2026-06, scored by anything
     other than the sealed primary lockbox;
   - `forward-confirmatory` (E3): real months after 2026-06, under ADR 0010 only.

   Code refuses to read 2020-01..2026-06 rows for a non-primary model unless the caller passes an
   explicit exploratory flag. Such a report starts with: *"EXPLORATORY: designed after these
   outcomes were seen; not evidence of improvement on these months."* E1 and E2 results never feed
   a selection rule for the product. They rank, explain and decide what to register for E3.

3. **Private execution.** This supersedes ADR 0006 §2 for the program. The agent does not read
   real-data outputs, including aggregates, until the owner clarifies permission. Real-data
   experiments are run by the owner on the private machine. Their reports:
   - stay under the private working root;
   - contain aggregates only, with cells under 25 loans suppressed;
   - contain no loan identifiers.

   Console output is limited to output paths and pass/fail status. The agent builds and tests
   every experiment on synthetic data first.

4. **Rolling-origin development (V1).** Origins `o` ∈ {2007-12, 2009-12, 2011-12, 2013-12,
   2015-12, 2017-12}. For each origin:
   - train on outcome months ≤ o−24;
   - tune and early-stop on o−23..o−12 (Validation A role);
   - make the cross-fitted temperature decision on o−11..o (Validation B role, ADR 0004 §7 rule);
   - evaluate on o+1..min(o+24, 2019-12).

   The rules match ADR 0004. Every fold fits every family (B1, B2, M1, X1, X2, X3, H1), on the
   training fraction of the primary run and the same loan-hash sample definition. Folds are
   reported individually, plus the worst fold and the number of fold wins. Folds overlap and are
   serially dependent, so no significance test is pooled across folds.

5. **Regimes** (public PMMS only, matched term, as of the end of t−1). D4 and the forward reports
   use these definitions:
   - level band of `market_rate_t1`: `<4.0`, `[4.0, 5.5)`, `[5.5, 7.0)`, `≥7.0` percent;
   - six-month change: `falling` ≤ −50 bp, `rising` ≥ +50 bp, else `stable`;
   - new low: the t−1 rate is below every month-end rate in t−61..t−2.

6. **Diagnostic flag rules.** These are fixed before any real-data run and are flags for review,
   never automatic model changes.

   | Diagnostic | A flag is raised when |
   |---|---|
   | D1 era encoding | A feature separates pre-2009 from 2009–2017 training rows with AUC ≥ 0.8 (single-feature rank AUC), or has PSI > 0.25 between training and any later window |
   | D2 incentive | The payoff hazard falls as incentive rises (ICE) in more than 1% of reference rows |
   | D2 burnout | The payoff hazard rises with burnout in more than 1% of reference rows |
   | D2 level at fixed incentive | Shifting the note and market rate together by +200 bp raises the mean payoff hazard by more than 10% relative |
   | D2 tail | Beyond the 0.5% support edge of incentive, the mean payoff hazard doesn't keep falling by at least 5% relative per −100 bp. Reported as "flat extrapolation"; informational |
   | D6 sampling / D7 seed stability | The SD across 5 samples or seeds exceeds ¼ of the smallest between-family log-loss gap, or exceeds 10% of the mean incentive response at any grid point |

7. **Applicability verdict (R1).** Monitored features: `incentive_bps`, `market_rate_t1`,
   `rate_change_6m_bps`, `loan_age`, `burnout_months`. Joint pairs: incentive × market rate,
   incentive × age, and incentive × 6-month change.

   Each row gets one status:
   - `outside`: any monitored feature lies outside the training 0.5–99.5% range;
   - `sparse`: otherwise, if its joint cell in any pair has fewer than 1,000 training rows or
     fewer than 20 training payoffs;
   - `supported`: neither.

   A batch or projection gets a balance-weighted verdict:

   | Verdict | Condition |
   |---|---|
   | `unsupported` | outside share ≥ 25% |
   | `extrapolating` | outside share ≥ 5%, or outside + sparse share ≥ 20%, or any monitored feature has PSI > 0.25 against training |
   | `supported` | otherwise |

   The verdict is shown with every projection and evaluation. It never changes the forecast
   silently.

8. **Reproducibility.** Every experiment manifest records:
   - the data-lock fingerprint and release;
   - the Git SHA and a dirty-tree flag;
   - the software lock digest and the DuckDB version (the training sample uses DuckDB `hash()`);
   - the feature-contract digest and derived-feature version;
   - every window, the configuration digest, seeds, and the training sample definition;
   - `evidence_class`.

   Experiment directories are written once. Re-running gives a new directory.

9. **Sample-stability design (D6).** Sample `k` keeps loans with
   `hash(loan_id) % 10000 ∈ [k·n, (k+1)·n)`, where `n = fraction × 10000`. Sample 0 is exactly the
   primary run's training sample.

10. **Registration gate for ADR 0010.** A candidate may be sealed for forward evaluation if:
    - it outputs a coherent simplex on every scored row;
    - every input passes historical-vs-scenario parity;
    - its artifacts reload bit-identically;
    - every D2 flag it raises is reported.

    Development results don't gate registration. Registering is cheap, and filtering on
    contaminated evidence would bias the forward test.

11. **Change control.** A threshold here can change only by a dated amendment made before the
    first real-data run of the affected experiment. After that run, a change needs a new
    experiment ID, and both results are reported.

## Consequences

The program can learn from the failure without rewriting it. The real-data evidence it produces
before E3 is development or exploratory by construction. The owner runs every real-data step, so
the agent's analysis is limited to code, synthetic data and public rates until permission is
clarified. Owner effort goes into running documented commands, not into reviewing routine
engineering.
