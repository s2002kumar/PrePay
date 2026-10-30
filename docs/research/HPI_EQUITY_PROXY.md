# Research extension: house-price appreciation and regional equity proxies

- Status: **investigated, not implemented**. The point-in-time and provenance requirements below
  were checked against primary sources on 2026-10-30. Implementation needs owner decision O3:
  MODELING §4 excludes "current LTV" from the locked feature contract.
- Hypothesis it would test: H-MISS (RELIABILITY_PLAN §4, rank 5). The model can't see borrower
  equity.

## 1. Economic justification

Equity governs whether a borrower *can* act on a rate incentive, and whether they want to move or
take cash out:

- **Negative or thin equity blocks refinancing.** Lenders cap the LTV of a new loan. After 2007
  many in-the-money borrowers couldn't refinance until HARP relaxed the cap. Caplin, Freeman and
  Tracy (1997, *Journal of Money, Credit and Banking*, "Collateral Damage: Refinancing
  Constraints and Regional Recessions") document refinancing suppressed by falling regional
  house prices. Peristiani et al. (1997, FRBNY *Economic Policy Review*, "Credit, Equity, and
  Mortgage Refinancings") find equity and credit constraints affect refinancing alongside the
  rate incentive.
- **Large equity gains encourage cash-out refinancing and moves.** This fits the 2020–2021 wave,
  where price appreciation was exceptional.

That is a mechanism for **both** failures:
- 2009–2012 training data taught a muted refinance response, partly because of negative equity,
  so the model underreacted in 2020–21;
- the mechanism behind 2022+ turnover (equity-rich borrowers locked in by rates) is different
  again.

It is a hypothesis. This note doesn't establish it.

## 2. Candidate sources (verified)

| Source | Geography and frequency | Point-in-time? | Provenance | Usable? |
|---|---|---|---|---|
| **ELTV** field in the SFLLD performance file | Loan, monthly | **No.** The user guide defines it via Freddie Mac's *proprietary* AVM and says "enhancements to our Automated Valuation Model (AVM) may also impact the estimated value of a property over time." There is no documented as-of guarantee for historical months | Proprietary, can't be reproduced | **No**, and it can't be projected for a scenario or a fictional pool |
| FHFA HPI, all-transactions, **state**, quarterly (FRED `XXSTHPI`) | State (SFLLD has `property_state`) | **Yes from 2008.** ALFRED keeps release vintages, with release dates from 2008-05-22 for CASTHPI; downloads are public | FHFA, public; ALFRED vintages by date | **Yes, 2008+.** Earlier months only have revised history |
| FHFA HPI, purchase-only, state, quarterly | State | Not checked in ALFRED here | FHFA, public | Possible; narrower (purchase-only) |
| FHFA HPI, all-transactions, **3-digit ZIP**, quarterly | ZIP3 (SFLLD has the 3-digit postal code) | **No known vintages.** FHFA labels it "developmental", and thin ZIP3s are replaced by state non-metro or other substitute indexes | FHFA, public | Only with revised history, so look-ahead |

Release lag: a vintage dated the first of a month holds the quarter that ended about two months
earlier (measured on all 36 sampled vintages). FHFA's 2026 calendar published 2026Q3 on
November 24, 2026, about 55 days after quarter end.

## 3. How much would revised history leak? (measured)

`docs/research/hpi_revisions.py` downloads 36 semiannual ALFRED vintages (2008-12..2026-06) of
the all-transactions state HPI for CA, FL, TX and OH. It compares the 4-quarter house-price
appreciation known in real time with the same quarter in the 2026-10 vintage:

| Quarter measured | Pairs | Mean \|revision\| | Median | p90 | Max |
|---|---:|---:|---:|---:|---:|
| Latest quarter in the vintage | 144 | 0.56 pp | 0.41 pp | 1.20 pp | **3.94 pp** (FL, 2008Q3) |
| Two quarters older | 144 | 0.68 pp | 0.49 pp | 1.43 pp | 3.27 pp |

All 15 revisions of 2 pp or more lowered the appreciation first published. They fall in quarters
of 2008, 2009 and 2018, and the largest are in 2008–09, when equity mattered most. So a model
trained on today's revised HPI would have seen the crisis-era falls more clearly than anyone
could in real time. **Only real-time vintages are defensible.**

## 4. What a defensible implementation would require

1. **Feature (proposal):** an estimated mark-to-market LTV built only from information known at
   the end of t−1:

   ```
   mtm_ltv(t) = contractual balance after (t−1) payments
                / (original UPB / original LTV × HPI_state[q*] / HPI_state[q_origination])
   ```

   - `q*` is the latest quarter published in the ALFRED vintage available at the end of t−1.
   - The contractual balance is computed from loan terms, *not* the observed balance, which the
     feature contract excludes. That keeps historical vs scenario parity.
2. **Data contract:** an adapter for ALFRED vintage CSVs (quarterly, per state) with retrieval
   metadata, a data lock and a point-in-time join test like the PMMS guard.
3. **Before 2008:** no vintages, so revised values are the only option. Either start the feature
   in 2008 and treat earlier months as missing, or use a ≥ 2-quarter extra lag and state the
   look-ahead bound measured in §3.
4. **Scenarios:** projections need a stated house-price path, for example 0% or ±5% a year. That
   is a new scenario input, labeled as an assumption, with its own out-of-support checks.
5. **Era-proxy risk:** house-price appreciation is itself strongly era-dependent (2004–05,
   2020–21). It must pass D1 era encoding and D2 probes like every other feature.

## 5. Recommendation

Don't implement it until the owner decides O3. If approved:

1. Add it as a **separate development arm** (H1 and X2 with `mtm_ltv`) on the V1 rolling-origin
   folds. The 2009-12 and 2011-12 folds hold the negative-equity period.
2. If it improves those folds without failing D1/D2, register it as a **late candidate** with
   its own seen-through month (ADR 0010 §8). It can never join the existing registration.

Reproduce the measurement (public data only):

```bash
python -I docs/research/hpi_revisions.py <empty-output-dir>
```
