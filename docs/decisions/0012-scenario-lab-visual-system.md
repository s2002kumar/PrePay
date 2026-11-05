# ADR 0012: Scenario Lab visual system (B+) and two served-label corrections

- Status: accepted
- Date: 2026-11-04
- Scope: `web/` (visual system, Scenario Lab, Model Quality framing, tests),
  `src/prepay/api/methodology.py` (served rule text), `src/prepay/api/service.py` (model-range names)

## Context

Prepay 1.0 (ADR 0011) shipped a correct but plain Scenario Lab:
- five equal stat tiles;
- four separate charts;
- a reliability table;
- the ledger hidden in a drawer.

The owner asked for a final visual milestone. The target: a professional mortgage analytics
interface that a general reader understands in about 30 seconds, and that a finance or engineering
reviewer can audit in about five minutes. The milestone could not change the engine, the model,
the data pipeline or the research protocol.

Two directions were explored as interactive prototypes on the project's private design canvas.
Both used the live synthetic responses:
- A, an institutional analytics workstation;
- B, a modern investment analytics platform.

The owner chose **B with two parts from A**: the cursor-linked inspector and the full
A / B / B − A comparison table.

Review of the existing UI found three defects in it, and two in the API:
- The composition chart re-scaled its y-axis when it toggled between A and B, so the two looked
  alike when their dollars were not.
- Its component colors reused the A/B series colors: scheduled principal was drawn in A's blue.
- Calendar-year buckets made the first projection year partial and visually small.
- `model_range.models` named the selected family twice (B2, B1, B2, M1).
- The served applicability rule read "≥ 20% outside or in joint cells…". The code tests
  outside + thinly supported ≥ 20%.

## Decisions

### 1. Information hierarchy (B+)

The Scenario Lab is ordered top to bottom:
1. **Composer.** Pool, the A and B steppers, swap, and horizon.
2. **Outcome.**
   - Support status first.
   - Then one headline: B's cash-WAL difference in years, sooner or later.
   - Then one paragraph of financial consequence.
   - Beside it, four A-vs-B dot comparisons on shared axes: cash WAL, principal back within
     24 months, still owed at month H, and interest accrued over months 1–H.
3. **Full comparison table (from A).** Collapsed by default. It lists A, B, B − A and each
   model-family range for every headline metric, with a reconciliation row.
4. **Principal returned over time.** % or USD, with a floating tooltip, next to the
   **inspector (from A)**. The inspector shows every served monthly field at the cursor month
   for A, B and B − A, the served formula of the selected row, and that month's identity residual.
5. **Why the scenarios differ.**
   - Rates: the input, with the pool's WAC as a reference.
   - CPR: the model, marked where scenario rates start to act.
   - Remaining balance: the result.
   - One cursor drives all of the above.
6. **Where today's balance goes.** Each side's B0 split into scheduled, payoffs, credit exits and
   still owed, with a table. A second view shows principal cash over time.
7. **How far to trust this.** The verdict, the outside and thin-support gauge with the rule's
   thresholds, inputs by feature, the model-family spread, and the served reasons verbatim.
8. **The monthly ledger.** Whole dollars, with totals and the balance check.
9. **Active model, assumptions and the served limitations.**

### 2. Every number is a served field or one named step

`web/src/derive.ts` holds the steps, and `derive.test.ts` unit-tests them. The derived values:
- **B − A:** the served `a_minus_b` with its sign flipped.
  - The one exception: principal returned through the horizon has no served delta, so it is the
    difference of the two served summaries.
- **Credit exits over the horizon:** Σ of the served monthly `credit_exit_principal_usd`.
- **Credit exits not yet resolved by the horizon:** Σ DC − Σ recoveries − Σ losses.
  - Checked against the served `pending_recoveries_horizon_usd = (1 − severity) × pending`.
- **Principal cash returned:** scheduled + payoffs + recoveries.
  - Equal to the served cumulative fraction × B0.
- **B0:** the first month's served beginning UPB.
- **Identity residuals:**
  - B0 − Σ SP − Σ PP − Σ DC − ending;
  - per month: begin − SP − PP − DC − end;
  - month-to-month chaining.
  These are shown in the composition, the table, the inspector and the ledger.

`e2e/reconcile.spec.ts` asks the live API for the same inputs and checks against the JSON:
- the raw value behind each displayed number (on `data-*` attributes);
- each B − A sign;
- the identities;
- the formatted text.

The static site must show the same text as the live app across five comparisons. Those
comparisons include the analytical tables, the inspector and the trust panel.

### 3. Model support cannot be missed

- **The support banner sits above the headline, with an icon and a label.** It is amber when a
  scenario is extrapolating and red when one is unsupported.
- **An unsupported scenario switches the outcome to range-first.**
  - The headline becomes the model-family cash-WAL range.
  - Point values become hollow dots.
  - That scenario's lines are dashed.
  - The consequence paragraph is withheld.
- **Verdict chips appear on the scenario cards.**

### 4. Model disagreement is drawn differently from uncertainty

Model-family spreads are hatched brackets with end caps, never shaded bands. Every place they
appear says "model-family spread", and the outcome footnote states "not a confidence interval".
The trust panel names the families.

### 5. Visual system

- **Type:** Geist and Geist Mono (OFL-1.1), with tabular figures.
  - They are self-hosted from pinned `@fontsource-variable` packages, so there are no
    third-party requests and the static CSP stays `font-src 'self'`.
  - The licenses are served at `/licenses/`.
- **Scenario identity:** A #2a78d6 and B #eb6834 in light; #3987e5 and #d95926 in dark.
- **Principal components:** scheduled neutral grey, payoffs aqua (#1baf7a / #199e70), credit plum
  (#a3499d / #b65aae).
- **Validation:** the dataviz palette validator ran against #ffffff, #0f1318 and #161b22.
  - Every pair passes, except that aqua on white has 2.82:1 contrast.
  - The remedy is the rule the validator obliges: components are always direct-labelled and
    have a table twin.
- **Status** (good, warn, crit) always carries an icon and a word.
- **Surfaces:** a cool neutral page, one border weight, and an 8–10 px radius. There is no
  decorative gradient or illustration.
- **Theme:** Auto, Light or Dark, chosen explicitly.

### 6. Principal cash by period

Periods are monthly up to 36 months. Beyond that they are **projection years**, so every bucket
has 12 months: months 1–12, 13–24, and so on, with a partial last year labelled as partial.
Previously they were calendar years. The A and B panels share one y-axis maximum.

### 7. Two served-label corrections (API text only; no estimate or rule changes)

- **`model_range.models`** names each family once, in served order. The selected family comes
  first. The spread is still the min and max over every projected member, so every estimate is
  unchanged. A regression test checks both points.
- **`metrics.reliability_verdict.formula`** is now generated from the constants `decide()` uses
  (`MIN_CELL_ROWS`, `MIN_CELL_PAYOFFS`, the three thresholds and the support quantiles), so it
  cannot drift.
  - It now states "the outside plus thinly supported share ≥ 20%".
  - It notes that pools are judged on row support, not PSI (ADR 0009 amendment 1).
  - A test checks the text and `decide()` at every threshold.

## Consequences

- The static grid, the static export and its exact-equality check are unchanged. So are
  GitHub Pages, the post-deploy browser check, the engine, the model and the bundle.
- The two corrected labels change the served JSON. Pages rebuilds the static responses from
  the API at deploy time, so the site picks them up automatically.
- The UI adds two runtime packages (fonts only). The production audit still runs in CI.
- The live container keeps custom ramps and credit inputs. The static site says, inside the
  assumptions disclosure, that it holds precomputed results only and simulates nothing in the
  browser.

## Not done (out of scope by the owner's brief)

- No new model families, data sources, financial formulas or features.
- No valuation, discounting, duration, MBS waterfall or live pricing.
- No change to the private forward evaluation.
