# Prepay in five minutes: a guided tour

**Live demo: <https://s2002kumar.github.io/PrePay/>** (fictional portfolios, synthetic-trained
model; nothing to install). This walkthrough explains the engineering pipeline;
its displayed values do **not** establish real-mortgage predictive accuracy.

## The pitch (30 seconds)

A 30-year mortgage rarely lasts 30 years: people move and refinance. Whoever holds a pool of
mortgages needs to know when the principal comes back, because that sets reinvestment risk,
interest income and duration. The answer depends on where interest rates go.

Prepay implements an end-to-end approach to that question:
- it ingests SFLLD-format loan histories and builds point-in-time features;
- it trains competing-risk models of monthly payoff and credit exits;
- it converts model probabilities into an audited monthly cash-flow ledger;
- it shows synthetic, hypothetical results in an interactive comparison tool.

The real Freddie Mac study is private and its selected model failed important
cross-regime validation checks. The public demo is an engineering demonstration,
not a tested estimate for investing or lending decisions.

It is built like production software: typed, tested against independent oracles, reproducible,
with every claim scoped to its evidence.

## Try it (3 minutes)

1. **Scenario Lab** (opens by default). The fictional 2023 pool holds loans with roughly 7%
   coupons. Scenario A keeps rates flat; scenario B drops them 100 bp.
   - The outcome card leads with the support status, then the answer in one line: how many years
     sooner (or later) principal comes back under B, by cash weighted-average life. One
     paragraph then states the financial consequence: more principal back within 24 months,
     less still owed, less interest accrued.
   - Beside it, four dots-on-a-line comparisons put A and B on one axis per metric. Hatched
     brackets show the spread across model families, labeled as disagreement, not a confidence
     interval.
2. **Change the inputs.** Step scenario B up to *+300 bp*: payoffs slow, and the cash
   weighted-average life stretches from about 7.6 to about 11.9 years. That scenario is flagged
   **unsupported**, because rates that high are outside the model's training data. The page
   switches to range-first: the headline becomes the model-family range, point values turn
   hollow and B's lines dashed. Switch the pool to the *2021 low-coupon pool*: its 3% loans are
   far out of the money, so every scenario is flagged as extrapolating or unsupported. Every view
   is a shareable URL.
3. **Move the cursor.** Drag across any chart, or use the arrow keys on it. The inspector beside
   the main chart shows every served monthly field for A, B and B − A at that month. Click a row
   for its served formula. The three "why" charts (rates, payoff speed, balance) follow the same
   cursor.
4. **Audit the numbers.**
   - *Where today's balance goes* splits the as-of balance into scheduled principal, early
     payoffs, credit exits (not cash) and the balance still owed, and shows that it adds back to
     the dollar.
   - *How far to trust this* shows each scenario's applicability verdict against the rule's
     thresholds.
   - *Full comparison table* and *Monthly ledger* open the complete figures.
5. **Model quality** shows how the served model was chosen, by a rule fixed before testing, and
   its one-time sealed holdout result, next to every baseline.
   **Methodology** defines every number with its unit and formula.

The public site is a static build: every response was computed by the real API and checked
against it. Custom rate paths and adjustable credit assumptions are in the full app, which runs
locally with one command (README).

## What is hard here, and how Prepay handles it

- **Look-ahead leakage.** Every feature for month *t* uses only data known at the end of
  *t−1*. A dbt test enforces it, a deliberately corrupted warehouse proves the test can fail,
  and a separate Python state machine reproduces every feature for historical and hypothetical
  paths.
- **Mislabeled outcomes.** Loan modifications, whole-loan sales and repurchases are censored,
  never counted as defaults. Fourteen golden cases written from the specification check the SQL
  and an independent Python labeler.
- **Money that doesn't add up.** The cash-flow engine is pure arithmetic. Conservation is
  checked on every projection. The engine matches a 60-digit Decimal oracle and an exact
  rational oracle, and the tests must catch eight deliberate bugs. The API's numbers are tested
  to be exactly the engine's.
- **Fooling yourself with evaluation.** Models are selected on 2018, calibrated on 2019, sealed,
  then opened once on later years. When the selected model lost to another candidate on that
  holdout, the report said so and was not rewritten.

## The honest part

On real Freddie Mac data, which is analyzed privately pending a terms review, the selected
model **failed** across rate regimes:
- it overpredicted payoffs after rates rose;
- it underpredicted the 2020–21 refinance wave.

Instead of retuning on the months it had already seen, the project:
1. diagnosed why: the rates of 2020 were outside anything in training;
2. added applicability verdicts to every projection;
3. built economically constrained challenger models;
4. pre-registered a one-shot test on months nobody has seen yet.

No improvement is claimed until that test runs. The public demo uses a synthetic-trained model
and makes no real-world accuracy claim.

## Code worth opening

| File | Why |
|---|---|
| [`src/prepay/finance/ledger.py`](../src/prepay/finance/ledger.py) | The pure cash-flow engine and its conservation check |
| [`tests/financial/test_rational_oracle.py`](../tests/financial/test_rational_oracle.py) | Exact-arithmetic oracle: 360 payments retire the balance exactly |
| [`transform/models/intermediate/int_exit_events.sql`](../transform/models/intermediate/int_exit_events.sql) | How an outcome is dated and labeled, in SQL |
| [`src/prepay/features/machine.py`](../src/prepay/features/machine.py) | One feature state machine for history and scenarios |
| [`src/prepay/api/service.py`](../src/prepay/api/service.py) | The projection service: model, assumptions, reliability, model range |
| [`src/prepay/api/static.py`](../src/prepay/api/static.py) | How the public site is generated and verified against the API |
| [`web/src/views/ScenarioLab.tsx`](../web/src/views/ScenarioLab.tsx) | The comparison UI |
| [`docs/decisions/`](decisions/) | Eleven architecture decision records |

## By the numbers

- Python 3.12, strict typing, over 400 Python tests, eleven ADRs.
- dbt on DuckDB for the data pipeline; scikit-learn and LightGBM for models; FastAPI and React
  for the product.
- Every pull request runs:
  - lint and type checks;
  - the full test suite on synthetic data;
  - a finance coverage gate;
  - browser tests with accessibility checks, on the live app and the static site;
  - CodeQL;
  - a scan that blocks restricted data from ever being published.

## Limits, stated plainly

- Portfolios are fictional. The served model is trained on synthetic data.
- Not a valuation, MBS cash-flow waterfall or investment tool.
- Partial prepayments (curtailments), delinquency cash timing and servicing aren't modeled.
- All reviews so far are self-reviews by the implementing agent. No independent review has
  taken place.

More depth: [How it works](HOW_IT_WORKS.md) · [Validation report](VALIDATION_REPORT.md) ·
[Status](STATUS.md) · [1.0 acceptance report](reviews/RELEASE_1.0_ACCEPTANCE.md)
