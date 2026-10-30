# Forward-evaluation audit (R2): intervals, monotonicity, tolerances

Date: 2026-10-30, **before** registration and before any forward month exists. Evidence here is
from simulation, synthetic data and the definitions themselves. No real outcome was used. The
resulting changes are ADR 0010 amendment 2. The comparison families, members and models are
unchanged.

## 1. Do loan-cluster intervals capture shared time dependence? **No.**

Rows of a loan-month panel share two kinds of dependence:

- **within a loan:** the same borrower over many months;
- **within a month:** every loan sees the same rates, seasonality and news.

ADR 0010 originally used a loan-cluster bootstrap. That treats the forward months as fixed.
A forward claim is about months like these, not only these twelve.

**Simulation** (`prepay.evaluation.inference.coverage_study`):
- unbalanced panels of 2,000 loans over 12 months;
- paired differences = loan effect (SD 1) + month effect (SD varied) + heavy-tailed noise
  (t₄, SD 1);
- 400 simulated panels × 400 bootstrap replicates per design;
- target: the 95% interval covers the population mean.

| Month-effect SD | Months | Loan-cluster | Month-block | **Two-way** | Width, two-way ÷ loan-cluster |
|---:|---:|---:|---:|---:|---:|
| 0 | 12 | 0.955 | 0.500 | **0.980** | 1.18 |
| 0.03 | 12 | 0.938 | 0.600 | **0.978** | 1.22 |
| 0.10 | 12 | **0.808** | 0.813 | **0.963** | 1.57 |
| 0.30 | 12 | **0.455** | 0.888 | **0.915** | 3.29 |
| 0.30 | 24 | **0.538** | 0.893 | **0.940** | 2.53 |

Readings:

- **Loan-cluster** coverage is nominal without month effects and **collapses** as they grow.
- **Month-block** (months only) fails in the opposite case.
- **Two-way** (pigeonhole: loan multiplicity × month multiplicity) stays close to nominal
  throughout. It is conservative without month effects, and slightly low with strong month
  effects and only 12 months. 24 months recover most of that.

**Does this matter in a rate-driven panel?** On the fictional synthetic world, for the paired
log-loss difference M1 − B2:

| Window (12 months) | Loan-cluster 95% CI | Two-way 95% CI | Width ratio |
|---|---|---|---:|
| 2020 | [0.00001, 0.00140] (M1 significantly worse) | [−0.00037, 0.00167] (not distinguishable) | 1.46 |
| 2023 | [−0.00020, 0.00157] | [−0.00085, 0.00210] | 1.66 |

The conclusion in 2020 reverses. Shared monthly shocks are a structural feature of prepayment
panels, because all loans see the same rate path. They are not a simulation artifact.

**Decision (amendment 2 §1).** Forward decisions use two-way intervals and the loan-cluster
interval is reported. Twelve months is a small number of time clusters, so even two-way
intervals are approximate, and the report says so. Development reports (V1) and segment A/E
intervals still use loan-cluster intervals. They are labeled as such, and they are too narrow
under month shocks (§5).

## 2. Is the final payoff probability monotone? **Only for H1.**

ADR 0008's table says "payoff probability non-decreasing in incentive" for X1. By construction,
only the payoff *hazard* `h` is constrained. The reported probability is
`p_prepay = (1 − c) · h`, and the credit hazard `c` is unconstrained (ADR 0008 §Structure). So
`p_prepay` falls wherever `c` rises faster than `h`.

Measured on a fictional DEV2017 run, 5,000 Validation-B reference rows, with a coherent
incentive grid from −400 to +300 bp (the market rate moves and the note stays fixed):

| Model | Rows with a decrease > 1e-6/month | Largest decrease (monthly probability) |
|---|---:|---:|
| X1 | 6.1% | 2.5e-5 |
| X2 | 4.6% | 3.2e-5 |
| X3 | 30.7% | 3.3e-5 |
| H1 | 0% | 0 |

- **Magnitude.** At most about 0.04 pp of annualized CPR. That is economically negligible, but
  it isn't zero, so "monotone payoff probability" is not a claim the X family can make.
- **H1 is exact,** because its credit model doesn't use incentive.
- **Under the F2 credit assumption** used in projections, `p_prepay = (1 − d) h` is exactly
  monotone for every factored model.

**Decision (amendment 2 §4).** Keep X1 and X2 as pre-registered, since ADR 0008 accepted an
unconstrained `c`. Report the share and the largest decrease for every model in every forward
report, at a materiality of 1e-6/month. `prepay experiment verify` reports the same property as
a boolean on real rows.

## 3. Do the business tolerances have defensible economic meanings?

| ID | Quantity and unit | What an error of the tolerance size means | Finding | Change |
|---|---|---|---|---|
| T1 | Mean monthly CPR-proxy bias, pp/yr | About 1 pp of balance a year paid off at the wrong time | Sound. Equal month weights; curtailments excluded on both sides | none |
| T2 | 12-month payoff incidence, pp of loans | Share of loans mis-forecast to pay off | Sound. Count-weighted (complements T3); censoring interpretability rule kept | none |
| T3 | Pool factor at 12 months, pp of t₀ balance | Dollar error in remaining balance per $100 | **Absolute 1 pp only.** In a refi wave (30 pp paydown) that is a 3% relative standard, against 15% for T1/T2 | `max(1 pp, 10% of observed paydown)` |
| T4 | Truncated WAL at 24 months, years | Timing of returned principal | **Absolute only**, same issue as T3 | `max(0.04 y, 10% of observed shortening)` |
| T5 | Share of poorly served segment cells | Error concentrated in sub-populations a skewed pool may hold | Defensible. Its loan-cluster A/E intervals are too narrow under month shocks, which makes the rule *stricter* | none; noted |
| T6 | Prepay ECE ≤ 2× calibration-window ECE | **No economic unit.** ECE scales with the base rate, so it moves with the regime. It also compared calibrated forward ECE with raw calibration-window ECE | **Replaced** | overall A/E ∈ [0.9, 1.1], and A/E ∈ [0.8, 1.25] for the slowest and fastest fifths |

**Sampling noise.** The tolerances apply to point estimates. Forward cohorts of the sample hold
10⁵–10⁶ loans, so the realized incidence's sampling error is far below 1 pp. Reports show the
intervals next to every point.

## 4. Other defects found and fixed before registration

| Defect | Risk | Fix |
|---|---|---|
| Members were located by the absolute path recorded at registration | Moving the artifacts after registration would make evaluation impossible, and re-registering after forward data exists isn't allowed | Members are identified by seal SHA-256, candidate digest and run ID; `--member LABEL=PATH` remaps them (tested: a swapped member is refused) |
| No dress rehearsal before the one opening | A crash or out-of-memory error half way through the opening | `prepay forward rehearse` (tested; writes nothing into `evaluations/`) |
| No way to check a member's implementation without reading results | Unverified members get registered | `prepay experiment verify`: boolean invariants only (tested) |

## 5. Known limitations that remain

- Only 12 forward months: two-way intervals with few time clusters undercover slightly when
  month effects dominate.
- V1 development reports and segment A/E intervals use loan-cluster intervals.
- The loan-hash training sample uses DuckDB's `hash()`, which is stable only under the pinned
  DuckDB version (recorded in manifests).
- The monotonicity materiality (1e-6/month) is a judgment: about 0.001 pp of CPR.

Reproduce:

```bash
uv run pytest tests/unit/test_inference.py tests/integration/test_forward.py
uv run python -c "from prepay.evaluation.inference import coverage_study as c; print(c(sd_month=0.1, simulations=400, replicates=400)['coverage'])"
```
