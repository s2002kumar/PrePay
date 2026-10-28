# ADR 0006: Real-data study: processing controls and pre-registered analysis plan

- Status: accepted. Written after the Release 48 sample was ingested and **before** any real-data
  model was trained, any validation window was scored, or any test window was read.
- Date: 2026-10-28
- Scope: the private real-data study. ADR 0002–0004 stay in force unchanged.

## Context

The owner supplied the Freddie Mac SFLLD Standard sample (Release 48 archives, 1999–2026). The
study has to verify the source, run the pipeline at full scale, audit labels and features, train
under ADR 0004, and evaluate once on the sealed 2020+ windows. It also covers the analyses ADR 0004
listed as not yet built: segments, credit sufficiency and cash-flow run-off. Every one of those
analyses is fixed here so that none can be shaped after seeing holdout outcomes.

## Decisions: processing controls

1. **Location.** Raw archives, bronze/silver/gold tables, runs, models and reports live in a private
   working root outside cloud-synced folders. Nothing derived from the files is committed, sent to
   CI, put in a container, or deployed.
2. **What the implementing agent sees.** The agent runs on a hosted model API. It reads only
   aggregate outputs: counts, rates and metrics over many loans. It never reads loan identifiers,
   individual records or per-loan feature vectors. Scripts and logs are written to emit aggregates
   only, and segment cells with fewer than 25 loans are suppressed. Whether this processing fits the
   terms the owner accepted is flagged for the owner's review.
3. **Publication.** No real-data number appears in this repository until the owner has reviewed the
   dataset terms. Public docs state process status only. The real-data review packet is private.

## Decisions: primary analysis (unchanged protocol)

4. ADR 0004 is applied as written: windows of MODELING §5, the four families, Validation A
   tuning and selection with the parsimony rule, cross-fitted calibration on Validation B, seal,
   then one lockbox opening.
5. **Training sample.** If full training data doesn't fit in memory, `--train-sample-fraction`
   keeps whole loans by stable hash. The largest of 1.0, 0.5, 0.25 or 0.1 that keeps training peak
   RSS under 10 GB on the 15.4 GB host is used. The choice depends only on memory, and the
   manifest records it. Validation and test windows are always scored in full.
6. **Profiling before the opening** covers outcomes only through 2019-12. Distributions of outcomes
   after 2019 (event rates, payoffs by month) are first computed when the lockbox opens. Label and
   feature audits may read every period, but they report only agreement between independent
   implementations, never outcome rates.

## Decisions: secondary analyses, evaluated in the same single opening

They are implemented and tested on synthetic data first, then frozen into the seal's evaluation
plan. They describe the sealed models and never change them.

7. **Segments.** Each test window is scored by model, for the selected model and all four
   families, within each of these segments:
   - vintage (first-payment year): ≤2008, 2009–2012, 2013–2016, 2017–2019, 2020–2021, 2022+
   - loan age (months): 1–12, 13–36, 37–60, 61–120, 121+
   - incentive (bps): <−200, [−200, −100), [−100, −25), [−25, 25), [25, 75), [75, 150), ≥150
   - credit score: <660, 660–719, 720–759, ≥760, missing
   - original LTV: ≤60, (60, 80], (80, 90], >90, missing
   - loan purpose (P, C, N, other) and term (15y, 20y, 30y)

   Each cell reports rows, loans, observed vs expected payoffs and credit events, and the payoff A/E
   ratio with a 95% loan-cluster bootstrap interval. It also reports log loss and the
   balance-weighted payoff-only CPR proxy, observed vs predicted. Cells with fewer than 25 loans are
   suppressed. Cells with fewer than 50 payoffs are marked low-event. A cell counts as **poorly
   served** when the selected model's A/E interval lies entirely outside [0.8, 1.25]. Poorly served
   cells are reported, not repaired.
8. **Credit-hazard sufficiency** is decided on training and validation counts only, before the
   opening. The credit hazard counts as a validated output only if training has at least 1,000
   credit dispositions and Validation A and B each have at least 100. Otherwise its scope is
   constrained:
   - credit metrics are reported as descriptive with an "insufficient events" label;
   - real-data projections must treat credit exits as an assumption, not a forecast.

   On test windows, credit metrics are reported only where a window has at least 100 credit events.
9. **Cash-flow run-off** is measured for the cohorts active at 2019-12, 2021-12 and 2023-12, over
   24 months. Projection modes are hindsight rates and as-of flat rates.
   - Observed balance is each cohort loan's reported current UPB, zero after its exit.
   - Projected balance is the model's survival times the contractual amortization of the t0 UPB at
     the t0 note rate over the remaining term.
   - A censored loan (modification, whole-loan sale, RPL securitization, defect) leaves both sides
     from its censoring month.
   - Reported: pool factor at 6/12/24 months, cumulative principal returned (pp error), and
     horizon-truncated weighted average life (years).
   - Principal is decomposed into full payoffs, amortization of continuing loans (observed includes
     curtailments, which the engine doesn't model) and credit-exit balances. Each part is compared
     separately.
   - Contractual interest accrual, cash recoveries and credit losses are **not** compared: the data
     contains no cash interest receipts, and severity and recovery lag are illustrative inputs.
     Observed loss fields are described, not used as validation.
10. **Informative censoring.** For each cohort, the 24-month payoff incidence is recomputed as
    bounds, assuming every censored loan (i) never pays off within the horizon or (ii) pays off in
    its censoring month. Censored and uncensored loans are also compared on credit score, LTV and
    incentive at t0. If the bounds straddle a model's projection, that cohort result is reported
    as not interpretable on that point.

## Decisions: the B1 investigation

11. The B1-vs-B2 diagnosis uses synthetic evidence that has already been opened, plus real
    training and validation data. The original synthetic reports stay unchanged. Any revised
    baseline or selection rule is declared in its own ADR before the real lockbox opens. It is
    trained as a separate run with its own seal and evaluated once on the same untouched test
    windows. The primary run's report remains the primary result.

## Consequences

The opening yields one primary report and pre-declared secondary tables. A secondary finding
can't retroactively change the selected model, its calibration, or the claims made for the
primary result. Analyses not listed here, if run after the opening, are labeled exploratory.
