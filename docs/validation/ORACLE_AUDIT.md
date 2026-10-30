# Independent-oracle audit (R2)

Date: 2026-10-30. Scope: mortgage event definitions, cash-flow conservation, amortization,
partial principal payments and scenario mechanics.

**What "independent" means here.** Each area is checked against an oracle that:
- is built from the specification text;
- uses different code, and where possible different arithmetic, from the implementation.

Every oracle was written by the same implementing agent. So this audit shows that the code
matches the spec as the agent reads it. **It does not replace a human reviewer's reading of the
spec.** All evidence is on synthetic or constructed data.

## Results

| Area | Oracle and what makes it different | Tests | Result |
|---|---|---|---|
| Event definitions (MODELING §2, ADR 0003) | **14 golden cases**, one per decision-table row. Each edits one clean loan's history; the expected status, exit event and *exact set of labeled months* are stated from the spec in terms of the edited row, not computed by any implementation. Both the dbt SQL and the Python label oracle must match | `tests/integration/test_spec_golden_cases.py` | **14/14 pass**, SQL and oracle |
| Event definitions at scale | Python decision-table oracle reading bronze directly vs dbt (existing) | `tests/integration/test_transform.py` | pass (all synthetic loans) |
| Amortization (FINANCIAL §2) | **Exact rational arithmetic** (`fractions.Fraction`): the annuity as an exact rational power, no rounding | `tests/financial/test_rational_oracle.py` | 360 months at 0/2/6/15% retire the balance **exactly**; the engine agrees within 1e-9 of balance |
| Ledger with competing exits, recoveries, losses | Same exact oracle, random hazards, severity 0.35, lag 7 | same | engine within 1e-9 of balance on every line; §2 identity `B = SP + PP + DC + B'` holds **exactly**; disposed principal equals recovered + lost + pending, exactly |
| WAL (FINANCIAL §5) | Exact cash and exposure-exit WAL from their formulas | same | engine within 1e-12 relative |
| Amortization and ledger (existing) | 60-digit Decimal oracle, Hypothesis properties, 8/8 mutation kills | `tests/financial/` | pass (95% line+branch coverage) |
| Partial principal (installments paid, both servicing conventions) | Exact rational installment-by-installment schedule | `test_rational_oracle.py::test_partial_principal_*` | pass for 0–3 installments, no-recast and recast |
| Curtailment inference method | Simulated paths with known curtailments, missed payments, catch-ups, pay-aheads and rounding | `tests/unit/test_curtailment.py` | the matching convention meets the pre-declared rule; mis-specification is shown to invent curtailments |
| Scenario paths (ARCHITECTURE §6) | Expected flat, parallel and custom paths and the t0 15-year spread written out directly | `tests/unit/test_scenario_mechanics.py` | pass; history never changes |
| Features along a hypothetical path (MODELING §4, ADR 0003 §6–§7, derived features) | **Naive per-row loops** from the definitions: market rate, incentive, 6-month change, burnout, SATO, age, remaining term, new opportunity, payment saving | same (3 scenarios × 3 loans × 36 months) | all equal within 1e-9 |
| Coupon invariance (FINANCIAL §3) | Note rate, SATO, age and remaining term across −200/0/+200 bp; month-1 contractual interest across scenarios | same | identical |
| Metamorphic rate response (FINANCIAL §6.8) | A level-free model monotone in incentive | same | lower rates return more principal from **month 2** and over 24 months |

**A mechanic made explicit by the audit:** month 1 of every projection uses the rate known at
the end of t0, which is history, so no scenario can change month 1. Scenarios act from month 2.
This is the point-in-time rule working as specified. The UI and methodology don't currently
mention it; that's tracked in the R2 report.

## Assumptions that remain unvalidated (and how each is labeled)

| Assumption | Why it can't be validated here | Label |
|---|---|---|
| Scheduled principal is paid before same-month exits | A simulation convention; real timing differs (FINANCIAL §2) | `assumptions.timing` in every API response |
| No curtailments in projections | The F1 real-data rule hasn't run | `assumptions.curtailments: not modeled`; CPR labeled full-payoff-only |
| Credit severity and recovery lag | Illustrative inputs; no cash-recovery ground truth | `credit_severity`, `recovery_lag_months` in the request and response |
| Credit-exit rate | Credit hazard not validated (ADR 0006 §8) | `assumptions.credit_exits: assumption: …` |
| Rate paths | User hypotheticals, not forecasts | scenario labels; methodology limitations |
| Contractual interest | Accrued, not collected | metric definition "accrued, not necessarily collected" |
| Behavior beyond training support | Extrapolation | applicability verdict and model range (R1–R3) |

Reproduce:

```bash
uv run pytest tests/integration/test_spec_golden_cases.py tests/financial/test_rational_oracle.py \
  tests/unit/test_scenario_mechanics.py tests/unit/test_curtailment.py
```
