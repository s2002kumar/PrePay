# ADR 0003: Event labels, quarantine and the gold hazard panel

- Status: accepted
- Date: 2026-10-28
- Scope: `transform/` dbt models; implements MODELING §2 and §4 without changing their definitions

## Context

MODELING §2 fixes the event taxonomy and its chronological decision table. It leaves several
operational details open: how to treat duplicates, records that end without a code, the first
observed month, and how to compute burnout and SATO from public rates without a loan × month
spine.

## Decisions

1. **Quarantine vs. exclusion.** A loan is *quarantined* (dropped, counted in
   `agg_data_quality`) for data problems the decision table forbids guessing around: orphan
   performance rows, no performance rows, duplicate origination IDs, any field-domain violation,
   missing required origination fields, conflicting duplicate periods, gaps, rows after
   termination, same-month modification + termination, a terminal code without an effective date,
   multiple terminal rows, or a `P` (prior modification) flag after entry with no earlier `Y`
   (amendment 1). A valid loan outside the modeled population is *excluded*:
   modification flag `P` on its first observed row, or a non-FRM / interest-only product.
2. **Exact duplicates are collapsed, not quarantined.** Identical rows for one loan-month carry
   no contradiction. The first source line is kept, and a dbt test reconciles bronze rows =
   blocked + collapsed + kept.
3. **Event month = reporting period of the record that carries the event.** If the zero-balance
   effective date differs from that period, the loan is counted (`zero_balance_date_mismatch`)
   but not quarantined. The guide says events are reported in the period of the effective date;
   real-data counts will show whether this needs revisiting.
4. **At-risk month.** Month `t` enters the panel only if the loan has a record at `t-1` that is
   non-terminal with UPB > 0, on or after the first payment month, and `t` is on or before the
   first event. A loan's first observed month therefore never carries a label (no observed prior
   state). The synthetic CI data has 2 such prepayments among 2,947.
5. **Censored months.** The month of a modification (`Y`) or a `15`/`16`/`96` record is excluded,
   since its P/C/A outcome is unobserved. Maturity months are excluded: the contract, not
   behavior, ends the loan. A loan whose records simply end (at the cutoff, or earlier with no
   code) was observed active in its last month, which is labeled A. The second case is reported as
   `censor_unexplained_end`.
6. **Burnout.** `burnout(t)` counts months `j ∈ [first_payment, t-1]` with
   `(note − matched-term PMMS at end of j−1) × 100 > 50`. It is computed as a difference of
   cumulative counts per distinct (note rate, rate series). That costs O(distinct notes × months)
   instead of a loan × month spine. Months before the rate history do not count.
7. **SATO** = note rate minus the matched-term PMMS at the end of the month before the first
   payment month (the last observation preceding first payment).
8. **Matched term.** Original terms ≤ 180 months use `MORTGAGE15US`; all others use
   `MORTGAGE30US`.
9. **Point-in-time guard.** A dbt test fails if any feature rate was observed after the end of
   `t-1`. Integration tests corrupt a copy of the warehouse and confirm this guard and the
   chronology guard both fail.

## Verification (synthetic)

- An independent Python implementation (`tests/integration/label_oracle.py`) reads bronze
  directly and must equal the SQL exactly: quarantine set, exclusion set, every event, every panel
  row and outcome.
- Every quarantine finding equals the generator's injected anomaly set for that kind.
- Panel outcomes agree with the generator's ground truth.
- Recomputing the generator's true hazard from the gold features reproduces it to within 1e-9.
  That only works if incentive, burnout, age, calendar month and borrower attributes are all
  aligned to `t-1` exactly as the generator used them.

## Amendment 1 (2026-10-28, before any real-data model was trained)

The private full-sample label audit (ADR 0006 §6) found the SQL and the independent Python
oracle disagreeing. DuckDB's `arg_min(flag, month)` skips rows whose flag is blank, so the SQL
"first row is `P`" test was really "first *non-blank* flag is `P`". That wrongly excluded loans
that show `P` only after entry. Such a loan reports a prior modification with no `Y` month, so its
modification month, and therefore its censoring time, is unknown. Real-data counts stay in the
private review packet (ADR 0006 §3).

- The SQL now uses `arg_min_null`.
- Such loans are quarantined as `prior_modification_without_y`, in SQL and in the oracle, rather
  than guessed into the panel. This follows the existing rule: data problems are quarantined and
  counted, never repaired.
- The synthetic generator never produces this pattern. A targeted test edits two loans in a copy
  of the synthetic source so both rules are exercised. The generator is left unchanged so
  published synthetic evidence stays exactly reproducible.

## Consequences

Everything that drops data is counted and attributed. The definitions are executable twice (SQL
and Python) and checked against a known truth. Real-data behavior of rules 3 and 5 is still to be
confirmed.
