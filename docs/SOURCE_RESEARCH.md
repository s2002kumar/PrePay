# Prepay | Source verification, regulatory context, and open questions

Checked 2026-10-27 using primary-source public pages and official documents. This is a research checklist, **not legal advice**.

## Confirmed official source facts

1. Freddie Mac public overview: historical Single-Family Loan-Level Dataset, 1999-2026 originations and *disclosed performance through March 31, 2026* according to the currently posted overview. The standard and non-standard products combined cover ~56m loans; **do not present this as the sample's size**. Registration to Clarity required for source files. https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset
2. July 2026 **Release 47** General User Guide: standard fixed-rate full-amortization product; sample randomly draws 50,000 loans per complete vintage, proportionate for partial vintages; sample naming `sample_YYYY.zip`, orig/perf files. Source fields have no header. https://www.freddiemac.com/fmac-resources/research/pdf/general_user_guide_july_2026.pdf
3. Same guide, PDF p.11: zero-balance `01=Prepaid or Matured`, `02=Third Party Sale`, `03=Short Sale or Charge Off`, `09=REO Disposition`, `15=Whole Loan Sales`, `16=Reperforming Loan Securitizations`, `96=Defect`. Modification `Y` marks this period, `P` marks prior modification—not borrower default. Delinquency `03` is 90-119 days but does **not** itself mean loan liquidation.
4. Freddie disclosure changes document, effective July 2026: column layout, enumeration and names changed under Release 47; implement the exact active release and do not reuse an older positional schema without review. https://www.freddiemac.com/fmac-resources/research/pdf/disclosure-changes-summary.pdf
5. Official Freddie terms (Nov 2025 revision): internal use is expressly constrained; public noncommercial academic/research results/related derivatives have conditions, and ordinary third-party distribution of original/derived products is restricted. It is **not** sufficient to aggregate to 25 loans. No security mapping/trading use. The default public demo must therefore be synthetic and not serve a real-trained model or Freddie-derived rep lines without specific clearance. https://capitalmarkets.freddiemac.com/crt/docs/pdfs/fre_terms_conditions_sflld.pdf
6. Freddie Mac changed PMMS on **November 17, 2022** from lender survey to loan-application-based estimates; FRED explains this change. https://fred.stlouisfed.org/news/2022/11/changes-to-freddie-mac-dataset-in-fred ; https://www.freddiemac.com/pmms
7. FRED series: https://fred.stlouisfed.org/series/MORTGAGE30US and https://fred.stlouisfed.org/series/MORTGAGE15US. Preserve original observation dates, retrieval details and units (percent/year).
8. New U.S. interagency model-risk guidance is **SR 26-2, Apr 17 2026**, replacing SR 11-7; relevant as a governance inspiration. https://www.federalreserve.gov/supervisionreg/srletters/sr2602.htm
9. OSFI Guideline E-23 revised September 11, 2025, takes effect **May 1, 2027** in Canada; use for model inventory/monitoring concepts, not a compliance badge. https://www.osfi-bsif.gc.ca/en/guidance/guidance-library/guideline-e-23-model-risk-management-2027
10. SEC filing example documents the common SMM denominator `(Beginning Principal - Scheduled Principal)` and CPR annualization, whereas loan-payoff-only proxies omit components seen in many securities definitions: https://www.sec.gov/Archives/edgar/data/1408974/000102024208000043/in07m412.htm

## Questions Claude must settle using downloaded files and documented evidence (not guessed)

- What *exact* official file layout bytes apply to this obtained sample ZIP release? Record URL/version/date and column test fixture. A publisher website hyperlink may not render in an automated browser, but the researcher must obtain a usable authoritative spec.
- Does this user's lawfully downloaded data follow July 2026 Release 47 or an older release? Does it contain all 1999-on vintage ZIPs and cutoff through March 2026? Do not assume.
- Are full payoff removal UPB and monthly balances complete and accurate enough for CPR proxy? Compare private balances to verified code and document nonreconciling events.
- Does user registration authorize a specific noncommercial public research *aggregate* report? Review terms and ask for legal clarification before public distribution of any derived assets or real-trained model.
- Are there enough observable dispositions within desired windows for stable 3-state forecasting? If not, de-scope terminal credit risk as modelled hazard and show an assumption instead.
- Do the complete data fit the user's machine? Profile actual memory and disk. Use partitioned processing; adopt only reproducible, documented, loan-consistent sampling if necessary.

## Negative findings against the initial draft

- Labeling whole-loan sale code `15` as default was factually incorrect.
- Labeling first modification `Y` as a credit-loss/default event was financially misleading.
- Treating 90+ delinquency as a terminal cash-loss event conflated temporary borrower distress and actual investor loss.
- Assuming any 'at least 25 mortgages' aggregation was universally permitted public redistribution lacked support in Freddie's terms.
- Publishing trained model weights, representative lines and a real-data API without release review risked violating dataset distribution rules.
- Two independent binary hazards followed by clipping `p+d<=1` can give mathematically incoherent/calibration-distorted probabilities.
- Requiring a GBM win on every untouched period encouraged data leakage and distorted reporting; empirical non-win is an equally valid research result.
- Treating credit-related disposition principal as immediately received cash, or treating hypothetical accrued interest as collected cash, would materially overstate financial certainty.

## Addendum: verified 2026-10-28 (implementation start)

Primary sources were fetched and checksummed when implementation began. See
`docs/decisions/0002-sflld-source-contract.md` for hashes and the resulting contract.

- **Release 48 is current.** Published 2026-10-28; origination and performance cutoff
  **2026-06-30** (the dataset page now says performance through June 30, 2026, superseding the
  March 31, 2026 figure above). Release 47 (2026-07-29) had cutoffs of 2026-03-31.
- The URL cited in item 2 (`general_user_guide_july_2026.pdf`) now serves the **Release 48**
  guide (October 2026). Its layout is identical to Release 47's: origination 31 fields,
  performance 35 fields. The official header files match `src/prepay/contracts/sflld.py`
  byte for byte.
- Release 47 changes that matter for parsing and labels: `Loan Sequence Number` became
  `Loan Identifier`; delinquency status is now two-character `00`, `01`, … with `RA` and
  `XX` = not available; payment deferral flag is `C`/`P` (was `Y`/`P`); recoveries and gains
  are now negative and expenses and losses positive; cumulative modification cost is disclosed every
  month after the first modification; postal code is three digits (`000` = unknown).
- Monthly reporting period conventions changed twice: cycles through April 2019 ran 16th–15th
  for scheduled P&I; May 2019–September 2025 used calendar months; from October 2025
  curtailments and prepayments received by the 2nd business day of the next month are included.
  For periods on or before September 2025, delinquency `00` can also mean "cycle before first
  payment date". These transitions line up with MODELING §5's flagged 2019-05 and 2025-10
  months.
- `Actual Loss` is computed for zero-balance codes 02, 03, 09 **and 15**, and set to null
  for dispositions in the three months before the performance cutoff.
- FRED PMMS CSV (`fredgraph.csv?id=MORTGAGE30US`) has the header `observation_date,MORTGAGE30US`,
  ISO dates, one row per weekly observation, and values in percent per year. As of 2026-10-22
  the 30-year rate was 7.32%.

Still open: whether this researcher's download is R47 or R48 (declared in `configs/data.lock.json`
at download time), trailing-delimiter behavior, and non-numeric Net Sales Proceeds markers.
