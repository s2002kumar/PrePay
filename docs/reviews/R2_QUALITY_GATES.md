# R2 quality-gate report: empirical development evidence and audit readiness

Prepared 2026-10-30, updated 2026-11-02 and 2026-11-07 (G15/G16 corrected: the development
queue stopped on 2026-11-03), by the implementing agent. **Self-review, not independent review.**

**Verdict: the forecasting model is not shown to be accurate and is not production-ready.**
R2 did three things:
- audited the forward test and the financial core;
- ran the development workflow on the private data, on the owner's machine;
- prepared the prospective comparison.

None of this produces confirmatory accuracy evidence. That can only come from months after
2026-06 (ADR 0010). After R2, research was frozen unless the owner decided otherwise (ADR 0011).
On 2026-11-07 the owner opened a separate Prepay 2.0 modeling research phase (ADR 0011
amendment 1, ADR 0013). Its first gate repairs G15 (`docs/reviews/PREPAY_2_GATE_A.md`).

**What the agent saw of private runs.** Under the owner's data-use instruction (ADR 0009 §3),
real-data jobs ran on the owner's machine through a blind runner. The agent read only:

- exit codes, wall time, peak RSS and SHA-256 digests;
- for failures, exception class names and code locations;
- for member verification, the names of failed implementation checks.

It read no metric, rate, distribution, coefficient or record. Every real-data result below is
therefore "ran; result private", never a number.

## Status legend

| Status | Meaning |
|---|---|
| VERIFIED | Shown by a reproducible check: test, simulation, public data or a digest. Not a real-data accuracy claim |
| DEVELOPMENT-ONLY | Ran on real outcome months ≤ 2019-12 (or as labeled), on the owner's machine. Results private and not read by the agent. Can rank and explain, never confirm (ADR 0009 §2) |
| FAILED | The check or claim doesn't hold as stated |
| BLOCKED | Waits for an owner decision or an outside dependency |
| FORWARD-VALIDATION-PENDING | Can only be decided on months after 2026-06 (ADR 0010) |

## Gates

| ID | Gate | Status | Evidence |
|---|---|---|---|
| G1 | Original sealed study and opened holdout results unchanged | **VERIFIED** | `load_seal` verifies the primary run against its artifacts (2026-10-30). `seal.json` `abb6e0fb…becd7` and `evaluations/first.json` `a746e0d9…1370c` are both read-only. No R2 job writes to the run |
| G2 | Forward decision intervals capture shared monthly shocks | **FAILED** as pre-registered → fixed before registration (ADR 0010 amendment 2) | Loan-cluster coverage 0.81 / 0.46 at month-effect SD 0.1 / 0.3; two-way 0.92–0.98 (400 × 400 simulations). On the synthetic world a "significantly worse" conclusion flips. `docs/validation/FORWARD_AUDIT.md`, #24 |
| G3 | Final payoff probability monotone in incentive | X1–X3: **FAILED** as a property (synthetic: 5–31% of rows decrease, ≤ 3.3e-5/month). H1: **VERIFIED** (exact) | Reported per model in every forward report and in `experiment verify`. ADR 0008's table corrected by amendment 2. Exact under the F2 credit assumption |
| G4 | Business tolerances have economic meaning | T1, T2, T5 **VERIFIED**. T3, T4 **FAILED** (absolute-only) → scaled to the regime. T6 **FAILED** (unitless ECE ratio) → replaced by quintile A/E | `FORWARD_AUDIT.md` §3 |
| G5 | Mortgage event definitions | **VERIFIED** (agent-authored oracles) | 14 spec golden cases reproduced by dbt SQL **and** the Python oracle; plus the full-panel oracle comparison. `ORACLE_AUDIT.md`, #25 |
| G6 | Cash-flow conservation and amortization | **VERIFIED** | Exact `Fraction` oracle: 360 months retire the balance exactly at 0/2/6/15%; every ledger line within 1e-9 of balance; §2 identity exact. Plus the Decimal oracle and 8/8 mutation kills |
| G7 | Partial principal payments (curtailments) | Method **VERIFIED** (synthetic rule passes). Real-data rule **DEVELOPMENT-ONLY**: ran 2026-10-30 (through 2019-12, and through 2026-06 labeled exploratory); the decision is in the private report, not read by the agent. Engine: not modeled | `test_curtailment.py`, `test_rational_oracle.py`, `CURTAILMENTS.md` |
| G8 | Scenario mechanics | **VERIFIED** | Naive-loop oracles for every feature on hypothetical paths; coupon invariance; monotone response from month 2. Month-1 timing now disclosed (#27) |
| G9 | Economic probes D1–D3 on the sealed primary run | **DEVELOPMENT-ONLY**: ran 2026-10-30, exit 0, 4 min, 3.9 GB peak | Private `reports/real/r2/diagnostics-primary.json`; not read by the agent |
| G10 | DEV2017 member trained by clean code and sealed | **VERIFIED** (engineering) | Exit 0, 86 min, 5.7 GB peak, worktree `15911c4` (clean), sealed |
| G11 | REFIT2026 member trained and sealed | **VERIFIED** (engineering; memory rule applied) | The first attempt used the primary run's fraction (2026-11-01, worktree `2a0d4e9`). It fitted M1, then B2's fit ran out of host memory (`_ArrayMemoryError` in scikit-learn's multinomial loss gradient), with under 1 GB free on a host shared with unrelated work. The runner then crashed before writing a status file; it now digests a printed run path only if it exists. Under ADR 0006 §5 / ADR 0010 §1 the next ladder fraction was used, **0.05**, chosen by memory only. That run: exit 0, 7.6 h, 3.2 GB peak, worktree `2a0d4e9` (clean), sealed 2026-11-02 23:22 UTC |
| G12 | Member implementation verification (boolean invariants) | **VERIFIED** (engineering) | `experiment verify`, 2026-11-02 23:23 UTC: DEV2017 and REFIT2026 both `all_pass: true`, no failed checks (exit 0, 1.2 / 2.4 GB peak). The agent read only `all_pass` and the failed-check names |
| G13 | Prospective comparison registered before any later release | **VERIFIED** | `forward register` exit 0 at 2026-11-02 23:23:51 UTC, after both members verified. The private data lock and store hold release 48 only: no later release had been downloaded. The owner confirms the registration file's contents (protocol step 3) |
| G14 | Rehearsal of the opening (time, memory) | **VERIFIED** (engineering) | `forward rehearse` on the members' own lock: exit 0, 78 min under host contention, 2.0 GB peak, finished 2026-11-03 00:41 UTC. Its metrics read months the members have seen, so they are not evidence; the agent did not read them |
| G15 | Rolling-origin development folds (V1) | **FAILED** (out of memory, 2026-11-03) → bounded-memory fix in Prepay 2.0 Gate A ([#43](https://github.com/s2002kumar/PrePay/pull/43)); not rerun | Queue C started 2026-11-03 00:41 UTC (worktree `dbcfb1d`, fraction 0.1, below-normal priority). Fold 2007-12 trained and was evaluated (about 02:23 UTC). Fold 2009-12 trained (08:31 UTC). Its evaluation failed about nine minutes later with `numpy._ArrayMemoryError`: B2's dense design (`design.dense` → `hstack`), inside the cohort backtest (`cohort.model_hazards`). Folds 2011-12 to 2017-12 never ran, and no summary was written (it is written after the last fold). No status file exists: the detached runner process, started 2026-10-30, still ran the runner code from before its 2026-11-02 fix and crashed on a printed fold label. The agent learned this on 2026-11-05 from exception class names and code locations only. Cause, fix and measurements: `docs/reviews/PREPAY_2_GATE_A.md` |
| G16 | Seed (D7) and loan-sample (D6) stability | **NOT RUN**: queue C stopped at G15 before these jobs | Re-planned as part of experiment E01 (ADR 0014, proposed) |
| G17 | House-price and equity proxies | **BLOCKED** (owner decision O3) | Research done: ELTV rejected (proprietary AVM, no as-of guarantee); state HPI has ALFRED vintages from 2008; real-time vs revised 4-quarter HPA differs by up to 3.94 pp. `docs/research/HPI_EQUITY_PROXY.md`, #26 |
| G18 | Any candidate more accurate than the sealed model (P1–P4, S1–S7); tolerances T1–T6 | **FORWARD-VALIDATION-PENDING** | First opening needs a release with cutoff ≥ 2027-06 |
| G19 | The sealed primary model is reliable across rate regimes | **FAILED** | Owner-reported from the private packet |
| G20 | Independent human review | **BLOCKED** (O4) | — |
| G21 | Permission for agent analysis of private aggregates; publication | **BLOCKED** (O5) | — |
| G22 | H1 fits within memory at REFIT scale | **FAILED** → fixed (#28) | Whole-fit peak −47% at 1.5M synthetic rows, same speed; chunked design equals the one-shot computation |

## Genuine unresolved engineering defects

| # | Defect | Effect | Status |
|---|---|---|---|
| 1 | The run-off `curtailment` line is a recast-convention residual | Overstates curtailments for no-recast loans in run-off reports (sealed lockbox, forward runoff). Not used by any tolerance | Documented in the definitions and `CURTAILMENTS.md`; code unchanged because the sealed evaluation used it |
| 2 | Segment A/E intervals (ADR 0006 §7 cells, T5) and the sealed lockbox use loan-cluster intervals only | Too narrow when months share shocks (G2). This makes "poorly served" verdicts stricter, not looser | Forward decisions (#24) and V1 fold tallies (#29) now use two-way intervals; segment cells and the frozen lockbox don't |
| 3 | X1–X3 final payoff probability is not monotone | Small (≤ 3.3e-5/month on synthetic data) but contradicts ADR 0008's table | Reported, not fixed (the pre-registered definitions stand) |
| 4 | The training sample uses DuckDB `hash()` | The sample is reproducible only under the pinned DuckDB | DuckDB version recorded in experiment manifests |
| 5 | The primary run manifest predates the `git_dirty` flag | Can't show the sealed primary was trained from a clean tree; its SHA is recorded | Unfixable without retraining; R2 members carry the flag |
| 6 | Categorical encoding looped over rows in Python | 5 s per million rows (synthetic), on every fit and prediction | **Fixed** in #30: one conversion per distinct value, and a property test shows the output identical to the row loop. Private R2 runs use earlier worktrees, whose outputs are identical |
| 7 | Forward evaluation holds every model's predictions for the whole window in memory | The rehearsal, the same code path over a 12-month window like the opening's, peaked at 2.0 GB (G14), well inside the 10 GB budget | **Closed by measurement**; code unchanged. A forward window with many more active loans would scale this peak |
| 8 | The synthetic world has no era effect | CI can't reward or punish H-ERA fixes end to end (only toy known-answer tests can) | Documented |
| 9 | Only 12 forward months | Two-way coverage about 0.91 under strong month effects | Stated in every forward report |
| 10 | B2 (multinomial logistic) exceeds host memory at REFIT scale and the primary fraction | REFIT2026 trains at a 0.05 sampling fraction, below DEV2017's (the primary run's) | Handled by the pre-registered ladder (G11), not by code. B2's fit is scikit-learn's |
| 11 | The owner's laptop is shared with unrelated work (about 37 GB committed on 15.4 GB) | Wall times, and which ladder fraction fits, depend on unrelated load | Recorded; private jobs run at below-normal priority |
| 12 | B2 and H1 built their whole dense design for every scoring call of up to 2^19 rows, and the fold evaluation held the full evaluation window and seven models' predictions while it ran the cohort and run-off backtests | Caused G15. At the cohort backtest's 480,000-row chunk, B2's transient alone measured 674 MiB on synthetic data (H1: 586 MiB) | **Fixed** in [#43](https://github.com/s2002kumar/PrePay/pull/43) (Gate A): design-model scoring in 65,536-row blocks (101 MiB and 136 MiB), and the backtests run before the window is loaded. On a synthetic fold all 2,586 reported values are bit-identical before and after |
| 13 | A failed command wrote no resource report | The G15 failure left no peak memory, so the failure couldn't be sized | **Fixed** in [#43](https://github.com/s2002kumar/PrePay/pull/43): the report is written for every exit, with the exit code |
| 14 | Peak RSS on Windows is the peak *working set* | On a host that pages heavily, Windows trims working sets, so peak RSS understates what a job committed. Windows refuses allocations at the *commit* limit. The peaks quoted in G9–G14 are working-set peaks | **Fixed** in [#43](https://github.com/s2002kumar/PrePay/pull/43): reports add `peak_commit_bytes` (Windows `PeakPagefileUsage`). Earlier peaks stay as recorded, labeled as working set |
| 15 | A detached queue keeps the runner code it started with, and the rolling-origin summary is written only after the last fold | G15 lost its status file, and a failure in any fold loses the summary of the folds before it | Open. ADR 0014 (proposed) starts every queue fresh from the fixed runner and adds resume from completed folds (Gate B) |

## Executable local review protocol

**Anyone, synthetic only, offline.** From a clean clone:

```bash
uv sync --frozen
make review      # make check + make test-finance + the audit tests + publication scan
# Windows without make: run the uv commands in the Makefile's `review` target
```

`make review` covers:
- lint, types, SQL lint and the full test suite;
- the finance coverage gate;
- the 14 spec golden cases;
- the exact rational finance oracle;
- scenario mechanics, the curtailment method and interval coverage;
- the known-answer probes and the forward-evaluation refusals;
- the publication scan.

**The owner, private.** In the private root (paths in RESEARCH_RUNBOOK §9):

1. **Integrity.** Recompute SHA-256 of the primary run's `seal.json` and
   `evaluations/first.json` and compare them with the digests under gate G1.
   `uv run python -c "from prepay.modeling.lockbox import load_seal; load_seal(<run>)"` must not
   raise.
2. **Members.** Open `reports/real/r2/verify-*.json`: `all_pass` must be true. The
   `properties` block holds the fitted-model monotonicity findings; the agent didn't read them.
3. **Registration.** `artifacts/forward/adr0010/forward-registration.json` must list REF,
   DEV2017 and REFIT2026 with their seal digests, `interval_method: two_way` and
   `seen_through: 2026-06`. Confirm that no release after 48 had been downloaded on its
   `registered_at_utc` date.
4. **Development evidence.**
   - Read `diagnostics-primary.json`: D1 flags, D2 `level_raises_payoffs` and
     `flat_extrapolation`, D3 verdicts for test windows A–C.
   - Read `rolling-origin-*.json` (per-fold `regime_calibration`, `cohort_attribution`,
     `aggregate`) and `stability-*.json`.

   These test H-ERA, H-SUP, H-CAL, H-RATE and H-SAMP. They don't confirm a candidate.
5. **Curtailments.** `curtailments-development.json → decision.defensible`. If it is false,
   curtailments stay unmodeled.
6. **Before the opening.** The rehearsal under `artifacts/forward/adr0010/rehearsals/` records
   stage times and peak RSS. Use its peak RSS to confirm the opening fits in memory.

## Owner actions

| ID | Action |
|---|---|
| O1 | Read the private development outputs (protocol step 4). Decide whether H-ERA/H-SUP evidence warrants anything beyond the registered forward test |
| O2 | When a release with cutoff ≥ 2027-06 appears: verify its layout, add it to `RELEASES`, lock, ingest, transform, then `prepay forward evaluate` once |
| O3 | Decide on the equity feature (`docs/research/HPI_EQUITY_PROXY.md`) |
| O4 | Invite an independent reviewer for R1, R2 and the audits |
| O5 | Clarify data-use permission (hosted AI analysis of aggregates; publication) |
