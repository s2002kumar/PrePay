# Prepay | Financial conventions and validation oracle

Version 2.0 • Implementation contract. Any change here requires documented justification and a new ledger version.

## 1. Economic scope

This engine forecasts **hypothetical monthly contractual and principal-flow outcomes** on fixed-rate loans, not actual collections, complete credit realization, a mortgage security waterfall or market value. A 90-day delinquency is not cash liquidation. A modification is not a credit loss. A note sale is not automatically default. Delinquent interest payment timing, unpaid interest and investor distribution mechanics are outside v1.

Credit-related terminal dispositions are separately modeled (codes `02`,`03`,`09`), but modelled loss/recovery amounts are illustrative assumptions unless independently calibrated on a legitimately permitted dataset. Loan-level observed losses, where disclosed, belong in *private* secondary research rather than the public demo by default.

## 2. Monthly timing (explicit choice)

- At start of month `t`: exposure `B_t` = end-previous-month outstanding principal; contractual annual note rate `c`; remaining contractual payments `n_t` including current month.
- Contractual monthly interest `I_t = B_t * (c/12)`. This is **accrued contractual interest**, not guaranteed received cash. Distinguish `contractual_interest` from realized collections everywhere.
- Compute level-payment scheduled principal for each active line as if it pays on schedule. For `i=c/12 >0`, monthly scheduled **payment** `A = B_t * i / (1 - (1+i)^(-n_t))` using stable `log1p`/`expm1` math, then scheduled principal `SP_t = min(B_t, max(0,A - I_t))`. For zero rate, `SP_t = B_t/n_t`. At final contractual month, force `SP=B` within cent tolerance.
- Exposure *after* scheduled amortization `R_t=B_t-SP_t`.
- Coherent mutually exclusive **month-t** hazards: `p_t`, `d_t`, `s_t`, where `p>=0,d>=0,s>=0` and `p+d+s=1` to tolerance. Do **not** clip and hide invalid hazards. Reject malformed probabilities.
- Expected full payoff principal `PP_t = p_t * R_t` and modeled credit disposition principal `DC_t = d_t * R_t`.
- Closing remaining balance `B_{t+1} = R_t - PP_t - DC_t`. Scheduled principal is paid once (not again inside payoff).
- Illustrative eventual credit recovery `RC_{t+L} = (1-severity) * DC_t`, with `severity` on `[0,1]`, explicitly configured `L` months. Illustrative loss = `severity*DC_t`. Real investors can have significantly different economics.
- For each month report `scheduled_principal`, `voluntary_prepay_principal`, `credit_exit_principal`, `recoveries_due/received`, `illustrative_credit_loss`, `contractual_interest_accrued`, `ending_upb`, scenario id, units/currency and assumptions.

At initial balance `B_0` the expected principal exposure conservation holds **each month**:

`B_t = SP_t + PP_t + DC_t + B_(t+1)`

A parallel economic cash ledger **must not** count credit-disposition principal both as recovered cash and as losses. Principal cash collected = scheduled + voluntary payoffs + delayed recoveries, and loss = principal not recovered from the illustrative disposition; `DC_t` is an **exposure termination** line, **not** an investor receipt.

For pools, sum absolute monetary line values; balance-weight averages are not a substitute for sum-of-loan economics unless approximation error is measured and reported.

**Convention limitation:** Treating scheduled payments as occurring before same-month exit is a simulation convention; actual timing differs. Therefore outcome-based hazard CPR and balance-based actual CPR must not be asserted identical without an observed-disposition-balance reconciliation. Publish a sensitivity check for alternative event timing when appropriate.

## 3. Coupon vs market rate

Changing the scenario mortgage rate changes future **incentives and modeled probabilities**, not the fixed mortgage's note coupon. Never recalculate existing mortgages' contractual coupons from PMMS. Rate scenarios can be outside the historical input range; return an out-of-support warning and uncertainty indication, not a claim of reliable precision.

## 4. Prepayment measures

**Model event hazard** `p_t` = conditional probability of **full voluntary early payoff** for an active loan. It is not automatically an observed pool SMM. For a balance-weighted month-t portfolio:

- Model SMM-style principal exit rate: `SMM_model(t) = Σ(PP_t)/Σ(R_t)` over eligible active lines (subject to nonzero denominator), from the monthly financial ledger.
- `CPR_model(t) = 1 - (1 - SMM_model(t))^12`.
- Credit disposition rate is measured separately, not hidden in prepayment.
- Actual full-payoff SMM can be approximated by the preceding balances and the same scheduled-principal convention; compare it against **actual zero-balance removal UPB** when available and quantify rounding/curtailment/deferral differences. Name this statistic `full_payoff_only_CPR_proxy`; do **not** call it an official security-level CPR.
- Industry SMM convention often uses beginning balance minus scheduled principal, and may include broader unscheduled principal definitions. Always label numerator/denominator and excluded curtailments. Never conflate count-weighted event rates with balance-weighted principal rates.

100% PSA: `CPR_PSA(age_months) = min(0.002 * age_months, 0.06)` (fraction/year); `SMM_PSA=1-(1-CPR_PSA)^(1/12)`. It is a **prepayment** benchmark only; credit exit baseline must be defined separately.

## 5. WAL and horizon metrics

Principal **cash** WAL in years (not just exposure cessation time): `WAL = Σ[(t/12) * (SP_t + PP_t + RC_t)] / Σ[SP_t + PP_t + RC_t]` for full-life flows when receipts are modeled. Also report `WAL_of_exposure_exits` for comparison, which includes credit exits and is a *different* estimand. For finite horizons, report `cash received to date`, `ending balance`, `pending recoveries`, and `censored/unreturned principal`; do **not** report the truncated cash WAL as full-life WAL.

Within assumption set, run whole life until all scheduled maturities and all recovery lags clear, or a documented finite maximum. A 24-month analysis displays cumulative returned principal fraction and remaining exposure plus lagged recoveries, not just WAL.

## 6. Independent finance test suite (required before ML integration)

1. 360-month amortization to zero at coupons 0%, 2%, 6%, 15%; compare to an independently implemented high-precision Decimal reference.
2. Edge `n=1`, very small positive coupon, high coupon, balance cents precision and zero balance.
3. Hazards p=d=0 => exact contractual amortization.
4. Hazards p=1,d=0 => entire after-scheduled exposure paid off; p=0,d=1 => entire exposure exits to disposition without being miscounted as cash receipt.
5. Arbitrary p,d probabilities in simplex: no NaN, negative balance, excess repayment or principal creation; identity per month within tolerance.
6. Recovery lag crossing horizon: unpaid pending recoveries carried in an explicit tail and cash WAL computed only when all receipts included.
7. Shock of market rates with fixed p,d held constant produces **identical** contractual cash flows (market rates do not change note coupons).
8. Feature/model shock that reduces payoff hazard (holding other things and assumptions fixed) must reduce same-month prepayment principal; global monotonicity of *all future metrics* is **not** mandated because burnout, future pool composition and nonlinear models can reverse effects.
9. Rep-line approximation benchmark against exact loan-level calculations across ≥5 diverse synthetic pool profiles; quantile error disclosed.
10. Independently seeded simulation: probabilistic Monte Carlo mean converges to deterministic expected ledger in smooth cases; confidence intervals are labeled sampling or model-uncertainty intervals, not guaranteed probability bands.
11. In 100% PSA with no credit exits, derived SMM produces the input PSA CPR to tolerance at each tested age.
12. Recorded monetary figures rounded only at output formatting; no hidden arbitrary `p+d>1` clipping.

## 7. Sensitivities and limitations to carry to UI

- Time of mortgage payments vs payoff, early payoff balances vs observed zero balance, omitted curtailments.
- Curing default/delinquency, unpaid scheduled interest, credit recovery timings and severity.
- Calibration under 2020 COVID mortgage forbearance and 2022 PMMS series methodology break.
- Rate paths are user hypotheticals, not market forecasts; no discounting/valuation.

No historical cash-flow-accuracy percentage may be published until evaluated against honestly available ground truth, including these omissions.
