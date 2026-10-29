# Can partial prepayments be measured from the source? (F1)

Status: **method built and validated on synthetic paths. Not yet shown defensible on real
data.** Until the real-data rule below passes, the finance engine models no curtailments and
every CPR is labeled `full_payoff_only_CPR_proxy`.

## Why it matters

The finance engine models full payoffs, not partial principal prepayments (curtailments). Real
pools have curtailments, so modeled principal timing runs slow, and the size of that bias is
unknown. The source discloses month-end balances, not principal receipts, so a curtailment can
only be **inferred**:

```
residual_t = (B_{t-1} − B_t) − scheduled principal of the installments paid in month t
```

## What the inference rests on

| Ingredient | Risk if ignored | How `prepay.evaluation.curtailment` handles it |
|---|---|---|
| Installments paid in the month | A missed payment followed by a catch-up looks like a negative, then a positive, "curtailment" | `k_t` = DDLPI advance (due date of last paid installment). The scheduled principal of exactly `k_t` installments is used; `k_t` outside [0, 12] is excluded |
| Servicing convention | Re-amortizing after a curtailment (**recast**) and keeping the original payment (**no recast**, the US fixed-rate norm) give different scheduled principal. The wrong choice invents a curtailment every month after a real one | Both conventions are implemented. Real-data rule uses no-recast. **The run-off decomposition's re-amortizing residual (RELIABILITY_PLAN A11) is the recast convention**, so on real loans it overstates curtailments |
| Disclosure rounding | Balances are rounded to $1,000 through loan age 6 | Months whose prior balance may be rounded (age ≤ 6) are excluded |
| Reporting-cycle changes | 2019-05: 16th–15th cycle → calendar month; 2025-10: prepayments received by the 2nd business day count in the prior month | Transition months are excluded and reported. Results are split by regime |
| Modifications, deferrals, forbearance | Contract terms or deferred balances change, so scheduled principal is unknown | Rows flagged modified, deferred or with non-interest-bearing UPB at t−1 or t are excluded |
| Terminal months | A payoff isn't a curtailment | Excluded |
| Cent rounding | ±1 cent noise | $1 dead band |

## Decision rule (pre-declared 2026-10-29, before any real-data run)

The method is **defensible for real data** only if both parts hold.

1. **Synthetic (CI).** On simulated paths with known curtailments, delinquency, catch-ups,
   pay-aheads, rounding and either convention, the matching-convention estimator reaches recall
   ≥ 0.90 and precision ≥ 0.95 for curtailments ≥ $500 in eligible months.
   - Status: **passes** (`tests/unit/test_curtailment.py`).
   - The same tests show that the wrong convention invents curtailments (precision < 0.5), and
     that ignoring DDLPI turns catch-ups into curtailments.
2. **Real data (owner-run).** In the calendar-month regime (2019-05..2025-09), under no-recast:
   - at least 90% of eligible one-installment months have a residual within $1 of zero;
   - at most 5% of eligible months have a negative residual beyond $1.

   This tests whether disclosed balances and DDLPI actually follow the contract arithmetic.
   - Status: **not run**.

If part 2 fails, curtailments stay unmodeled. The report then says which assumption broke:
convention, DDLPI semantics, or disclosure.

## Run it (private)

```bash
uv run prepay diagnose curtailments --data-root <data-root> --lock configs/data.lock.json \
  --out reports/real/curtailments.json --through 2019-12 --sample-fraction 0.02
```

The report holds aggregates only:
- eligibility and exclusion counts;
- quantiles of one-installment residuals;
- the share within the dead band and of negative residuals;
- the share of months with an inferred curtailment, and the implied curtailment SMM.

Each is split by reporting regime and loan age, for both conventions, with the decision. The
default stops at 2019-12; later months can be added once the opened windows' use is settled
(ADR 0009 §2).

## What this does not do

- It doesn't add curtailments to the engine. That is a separate change to the financial
  conventions, and it needs the rule above to pass first.
- It can't detect curtailments inside rounded months or in months with modifications, deferrals
  or forbearance.
- On the synthetic world it can't validate the no-recast branch: the synthetic generator recasts
  (SYNTHETIC_DATA.md). That branch is validated on the simulated paths in the unit tests.
