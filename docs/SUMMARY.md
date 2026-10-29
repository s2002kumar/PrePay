# Prepay in one page

**Problem.** Mortgage holders care about *when* principal comes back. Borrowers refinance when
rates fall and stay put when rates rise, so a pool's cash timing depends on the rate path.
Getting it wrong means reinvesting early at lower rates, or holding capital longer than planned.

**What I built.** An end-to-end research system and a public demo:

- **Data engineering:** a checksummed data lock and streaming ingest of Freddie Mac's
  loan-level files, using a layout verified byte for byte against the official Release 47/48
  headers. dbt on DuckDB quarantines bad records, dates each loan's first event, and builds an
  at-risk panel whose features use only information known the month before.
- **Machine learning:** competing-risk models for monthly payoff vs credit disposition vs
  staying active: PSA benchmark, smoothed lookup, spline logistic regression, joint LightGBM.
  Models are selected on 2018 by a rule fixed in advance, calibrated on 2019 only if
  cross-fitting says so, then sealed and evaluated once on 2020+, with Aalen–Johansen cohort
  run-off checks.
- **Quantitative finance:** a pure cash-flow engine (scheduled principal, payoffs, credit exits,
  lagged recoveries, WAL, CPR/PSA) checked against an independent 60-digit Decimal oracle and
  mutation tests. Rate shocks change behavior, never contract coupons.
- **Product:** a FastAPI service and React UI comparing two rate scenarios for fictional pools,
  keyboard accessible, mobile responsive, light and dark, tested with Playwright and axe.

**How correctness is shown.** Every major claim has a second, independent check: SQL labels vs a
plain-Python decision table; dbt features vs a separate state machine; gold features reproducing
a synthetic world's true hazards to 1e-9; money conservation vs a Decimal oracle; data-quality
rules vs deliberately injected anomalies. Leakage guards are shown to fail on corrupted data.

**What is honest about the results.** All published evidence is on **synthetic** data. The
Freddie Mac files arrived on 2026-10-28, and that study runs privately until the dataset terms
are reviewed. In the small synthetic world, the model my pre-registered parsimony rule picked
**lost** to the logistic baseline in the sealed holdout. The immutable first report says so, and
the rule wasn't tuned afterwards. In a world with 8× the data, the same rule picked the logistic
model, which won. That model has the same functional form as the synthetic truth, so the win
was expected and says nothing about real loans.

**When the real model failed.** On real data, the selected LightGBM:
- overpredicted payoffs after rates rose;
- underpredicted the 2020–21 refinance wave.

I didn't retune it on those months. Public rate history showed why that would be circular:
every training month above 5.5% was before 2009, and the 2020 rates were below anything in
training. So I built a reliability program instead:
- probes that catch a model using rate level as an era proxy (shown on a planted confound);
- constrained models that can't;
- an applicability verdict and a model-family range on every projection;
- a pre-registered one-shot test on months nobody has seen yet.

No improvement is claimed until that test runs.

**Engineering.** Python 3.12, uv, mypy --strict, ruff, sqlfluff, 270+ Python tests (Hypothesis
properties, mutation kills), Vitest, Playwright + axe. CI runs synthetic-only with SHA-pinned
actions and a read-only token. CodeQL, Dependabot and secret scanning are on; `main` is protected
with required checks. A publication gate scans tracked files, history and build outputs. The
container is digest-pinned, non-root, with a health check. Decisions are recorded in eight ADRs.

**Limitations.** The real-data study ran privately and is unpublished pending a terms review.
Not hosted yet. Not an MBS valuation or advice tool.
No independent human review has happened yet.
