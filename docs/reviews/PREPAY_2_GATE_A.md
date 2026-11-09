# Prepay 2.0 Gate A: the failed development queue, its repair, and the E01 specification

Prepared 2026-11-07 by the implementing agent, for the owner's review. **Self-review, not
independent review.** The evidence is synthetic data, public FRED rates and private-run
*metadata* only. No real-data output was read (ADR 0009 §3), and **no private job was launched
in Gate A**.

## Verdict

**Gate A is complete and ready for review.**

| Gate A item (ADR 0013, D4) | Result |
|---|---|
| Audit the failed queue | Done. Root cause identified from the code and the runner's sanitized failure summary (§1) |
| Implement and test the bounded-memory correction | Done: [#43](https://github.com/s2002kumar/PrePay/pull/43). Every reported value of a synthetic fold is bit-identical before and after. Scoring transients fall by 77–85%, and the evaluation's peak commit above baseline falls from 0.86 to 0.47 GB (§2, §3) |
| Correct the stale G15/G16 status | Done. G15 is FAILED and G16 NOT RUN in the R2 report; `STATUS.md`, the README and the 1.0 acceptance report are corrected (§4) |
| Prepare the exact E01 execution specification | Done: ADR 0014 (proposed then; accepted with revisions on 2026-11-09). Regime-shift folds are fixed now from public rates (§5) |
| Inquiry to Freddie Mac (D1) | Drafted in the owner's private notes, **not sent** |

Not done, as instructed:
- no private training or evaluation;
- no website work;
- no B-lite (D3).

The static data contract (D2) waits for E01's report schema, so that the public contract mirrors
what E01 actually produces.

## 1. Audit of the failed queue

### What the agent read

- Names, sizes and times of files in the private root.
- The blind runner's status files: exit codes, times, peaks, digests.
- The runner's stderr. It holds a runner traceback with code lines and a fold label only.
- The runner's own sanitizer (`_sanitized_failure`) applied to the private job log. It gave
  exception class names and `prepay` code locations, and nothing from the log's messages or
  values.

### Timeline (UTC)

| When | Event | Evidence |
|---|---|---|
| 2026-10-30 09:36 | The detached queue-C process starts and waits for queue B to finish | Creation time of its output file |
| 2026-11-02 | The runner is fixed to digest a printed run path only if it exists (R2 G11). The waiting process keeps the old code | Runner backup dated 2026-11-02 |
| 2026-11-03 00:41 | Queue B finishes; queue C starts rolling-origin at worktree `dbcfb1d`, fraction 0.1 | `status/queue-b.done` |
| 01:35 | Fold 2007-12 trained (about 54 min) | Run ID `20261103T013552Z-V1-2007-12-d618e7d4` |
| about 02:23 | Fold 2007-12 evaluated (about 48 min) | Its `evaluations/` directory |
| 08:31 | Fold 2009-12 trained (about 6.1 h) | Run ID `20261103T083135Z-V1-2009-12-0b39569d` |
| about 08:40 | Fold 2009-12's evaluation fails with `numpy._core._exceptions._ArrayMemoryError` | Sanitized frames (below) |
| about 08:40 | The runner crashes digesting `V1-2009-12`, a fold label it took for a run path, with the old code. No status file is written | Runner stderr |
| — | Folds 2011-12 to 2017-12, the seed and sample stability jobs, and the rolling-origin summary never ran | Absent outputs |
| 2026-11-05 | The agent finds the stop while auditing for ADR 0013 | ADR 0013 §13 |

Sanitized failure path, innermost last, at `dbcfb1d`. Scoring-wrapper frames are collapsed:
which wrapper a fold's model carries is a property of a model fitted on real data.

```
experiment.py:508  evaluate_development  -> cohort_backtest(...)
cohort.py:306      backtest              -> model_incidence(...)
cohort.py:202      model_incidence       -> model_hazards(...)
cohort.py:177      model_hazards         -> model.predict_proba(480,000-row chunk)
models.py          predict_proba / scoring wrappers
models.py:182      LogisticModel._predict_block (B2) -> preprocessor.dense(batch) @ coef
design.py:105      Preprocessor.dense    -> np.hstack(blocks)        _ArrayMemoryError
```

### Root causes

1. **B2 built its whole design for each scoring call.**
   - `HazardModel.predict_proba` scored up to 2^19 rows in one block.
   - The cohort backtest scores 20,000 loans × 24 months = **480,000 rows** per call.
   - For those rows, B2's `dense()` holds every piece (numerics, one-hot blocks, spline bases)
     and then copies them all into the final matrix with `hstack`. Measured on synthetic data at
     that size: **674 MiB** for that one call. H1 has the same pattern, at 586 MiB.
2. **The two phases of the fold evaluation stacked.** `evaluate_development` loaded the full
   evaluation window and computed seven models' predictions. It then ran the cohort and run-off
   backtests while all of that stayed in memory. Its peak was the sum of the two phases, plus
   the transient of cause 1.
3. **The host's commit headroom is small and variable.** Windows refuses an allocation when the
   system *commit* limit is reached.
   - Measured during normal use on 2026-11-07: **9.6 GiB** free out of a 63.4 GiB limit, with
     0.3 GB of physical memory free.
   - The headroom at 08:40 on 2026-11-03 is unknown.
4. **The failure couldn't be sized.**
   - The CLI wrote its resource report only on success.
   - On Windows, "peak RSS" is the peak *working set*. On a host that pages heavily, that
     understates what a job committed.
5. **The queue was fragile.**
   - A long-lived detached process kept pre-fix runner code.
   - The rolling-origin summary is written only after the last fold.
   - There is no resume.

### What is kept and what was lost

- **Kept, unchanged:**
  - fold 2007-12: trained, with a V1 evaluation report;
  - fold 2009-12: trained, never evaluated;
  - the sealed primary run, DEV2017, REFIT2026 and the 2026-11-02 registration. None was
    touched.
- **Lost:** time, and the folds and stability jobs that never started.

Under E01 (ADR 0014) every fold is retrained fresh at one code version. The V1 runs remain as
provenance.

## 2. The fix ([#43](https://github.com/s2002kumar/PrePay/pull/43))

| Change | File | Why it changes no number |
|---|---|---|
| Models with a dense design score in blocks of 65,536 rows: B2 (`DESIGN_BLOCK_ROWS`) and H1 (one design chunk per block). LightGBM families keep 2^19 | `modeling/models.py`, `modeling/challengers.py` | Rows are scored independently. The design rows are identical; only the matrix product is split. B2 is bit-identical on the measured chunk. H1 differs by at most 6.7e-16 in probability (float64 rounding). The existing block test now also forces ragged design blocks |
| The fold evaluation runs the cohort and run-off backtests **before** it loads the evaluation window and the predictions. After each stage it records the elapsed seconds and the process's cumulative peak working set and peak commit in `stages`. These are high-water marks, not per-stage peaks | `modeling/experiment.py` | The backtests use only statics, the cohort and the rate paths, with their own fixed seeds. Their computations are independent of the window and the predictions |
| The resource report is written for **every** exit, with `exit_code`, and adds `peak_commit_bytes` (Windows `PeakPagefileUsage`; `None` elsewhere) | `cli.py`, `resources.py` | Measurement only |

The forward evaluator (`evaluation/forward.py`) and the sealed lockbox (`modeling/lockbox.py`)
are not modified. They share `predict_proba`, so their scoring now uses the same blocks. That
changes probabilities by float64 rounding at most, and the registration binds the members'
artifacts by digest, not the code.

## 3. Evidence

### 3.1 Tests (synthetic)

| Test | Pins |
|---|---|
| `test_block_scoring_equals_a_single_pass` (extended) | Every family equals a single pass when the LightGBM and design blocks are both ragged |
| `test_dense_design_scoring_memory_is_bounded_by_the_block` | B2's traced peak is below a quarter of the old single pass's, and inside a bound set by one block. The old path materialized the full design |
| `test_h1_scores_in_design_blocks_with_bounded_memory` | The same for H1 |
| `test_cli_writes_resource_report_when_the_command_fails` | A failing command still writes its report, with `exit_code` 1 |
| `test_peak_commit_grows_with_committed_allocation` (Windows) | Committing 64 MiB raises `peak_commit_bytes` by at least 60 MiB |
| `test_rolling_origin_reads_development_months_only` (extended) | The stage order is load → cohort → run-off → read window → predict → metrics, and the peaks never decrease |

Local results on the fix branch:
- ruff, `ruff format --check` and `mypy --strict` are clean;
- the full suite result is in [#43](https://github.com/s2002kumar/PrePay/pull/43), with its CI run.

### 3.2 Numerical identity

The synthetic setup:
- `prepay synth --preset dev`: 47,000 fictional loans;
- one V1 fold, origin 2009-12, fraction 0.1, trained once;
- the same run directory evaluated four times, alternating the code at `main` (`cefbc70`, a
  clean worktree) with the fix branch. Each process printed the `prepay` it imported.

| Comparison | Values compared | Differing |
|---|---:|---:|
| main vs fix | 2,586 | **0** |
| main vs main (repeat) | 2,586 | 0 |
| fix vs fix (repeat) | 2,586 | 0 |

The comparison covers every number in the development report: metrics, paired intervals,
regime cells, cohort and run-off backtests and their attribution. Only the new `stages` block is
excluded.

### 3.3 Resources (synthetic, this laptop, 2026-11-07)

**One cohort-backtest chunk, 480,000 rows** (tracemalloc peak of a single scoring call):

| Model | Old peak | New peak | Old time | New time | Max abs. difference |
|---|---:|---:|---:|---:|---:|
| B2 | 674 MiB | **101 MiB** | 3.84 s | 3.48 s | 0 (bit-identical) |
| H1 | 586 MiB | **136 MiB** | 5.66 s | 4.74 s | 6.7e-16 |

**Whole fold evaluation**, measured from the operating system. The process baseline after
imports is about 1.49 GB of commit.

| Round | Code | Peak working set | Peak commit | Commit above baseline | Time |
|---|---|---:|---:|---:|---:|
| 1 | main | 1.03 GB | 2.35 GB | 0.86 GB | 78 s |
| 1 | fix | 0.52 GB | 1.96 GB | **0.48 GB** | 77 s |
| 2 | main | 1.02 GB | 2.35 GB | 0.87 GB | 98 s |
| 2 | fix | 0.47 GB | 1.96 GB | **0.47 GB** | 86 s |

With the fix, the peak is set by the run-off backtest. Reading the window, predicting and
computing metrics don't raise it at this scale.

### 3.4 What these measurements don't show

- **The real-scale peak.**
  - The evaluation-window phase grows with the number of evaluation rows. By array sizes it
    holds about 450 bytes per row for seven models.
  - On 52,688 to 205,425 synthetic rows, that phase measured 119 to 172 MiB held and 219 to
    300 MiB at its peak. Fixed costs (model loading, allocator reserve) dominate at those sizes,
    so the measurements give no reliable per-row slope.
  - Real cohorts and windows are larger. E01's pilot (Gate C) measures the real peak before any
    other fold runs.
- **Real-data behavior of any model.** The synthetic world says nothing about it.
- **Why the old runner crashed in detail.** The runner itself is outside this repository. A
  fresh queue process after each code change is an E01 condition.

## 4. Status corrections

| File | Correction |
|---|---|
| `docs/reviews/R2_QUALITY_GATES.md` | G15 **FAILED** (out of memory, 2026-11-03), with the timeline. G16 **NOT RUN**. New defects 12–15. Peaks G9–G14 labeled as working set |
| `docs/STATUS.md` | The rolling-origin row now says "stopped 2026-11-03". New Prepay 2.0 gate table. B+ shown as merged and deployed (#38, Pages run 41939981406) |
| `README.md` | "Research is frozen after R2" replaced by the Prepay 2.0 statement |
| `docs/reviews/RELEASE_1.0_ACCEPTANCE.md` | Dated corrections to "in progress" and to the research freeze |
| ADR 0011, ADR 0012 | Amendment 1 each (D5) |
| ADR 0013 | Decision record (D1–D5), and the frontend navigation proposal |

## 5. E01 in one paragraph

ADR 0014 pre-registers E01 on the six ADR 0009 rolling-origin folds, from public rates and
before any run:
- **Four regime-shift folds.** Their evaluation rates lie below the training range in 10, 24, 24
  and 11 of 24 months. 2010–11 and 2012–13 are the closest analogues of 2020–21.
- **Two in-support control folds.**
- **The lock-in case is not covered.** No fold has rates above its training maximum, so E01 can
  test the 2020–21 failure mode far better than the 2022+ one.

E01 compares B2, M1, X1–X3 and H1, with B0 and B1 as references. It uses dependence-aware
intervals throughout, payoff A/E and CPR error, cohort and balance run-off, the D2/D3 probes and
G16 stability. Its reading rules R1–R7, computed by the report itself, can at most nominate a
model for a later, separate forward registration.

Before any private job it needs:
- Gate B: engineering and a synthetic dry run;
- Gate C: an owner-run pilot fold, which must reproduce the existing fold 2007-12 model files
  byte for byte and stay under a 10 GiB peak commit.

## 6. Owner decisions

1. **The fix.** Review [#43](https://github.com/s2002kumar/PrePay/pull/43). Merging it rebuilds the public site from the same synthetic
   bundle. Rendered numbers can differ only through float64 rounding in B2's matrix products.
2. **This documentation.** Review it: the status corrections, ADR amendments, ADR 0013 decision
   record, ADR 0014 and this report.
3. **E01.** Decide E01-D1 to E01-D6 (ADR 0014 §10). E01-D1, who reads E01's results, is the one
   that most affects how much of the research the agent can do.
4. **The inquiry.** Review the draft at `notes/FREDDIE_MAC_INQUIRY_DRAFT.md`, and send it when
   ready.

## 7. Reproduce (synthetic, Windows for the commit measures)

```bash
uv run prepay synth --preset dev --out <w>/source
uv run prepay data-lock create --raw-dir <w>/source/raw --synthetic-manifest <w>/source/manifest.json --out <w>/data.lock.json
uv run prepay ingest --raw-dir <w>/source/raw --lock <w>/data.lock.json --data-root <w>
uv run prepay transform --data-root <w> --lock <w>/data.lock.json --memory-limit 3GB
uv run prepay experiment rolling-origin --data-root <w> --lock <w>/data.lock.json --out <w>/experiments --train-sample-fraction 0.1 --origins 2009-12
# Old code: a clean worktree of main on PYTHONPATH (check the printed prepay path); new code: this branch
python docs/reviews/gate-a/measure_fold_evaluation.py <w>/experiments/<run> <w> <w>/data.lock.json old.json
python docs/reviews/gate-a/measure_fold_evaluation.py <w>/experiments/<run> <w> <w>/data.lock.json new.json
python docs/reviews/gate-a/compare_reports.py old.json new.json
python docs/reviews/gate-a/chunk_scoring.py <w>/experiments/<run> <w>
python docs/reviews/gate-a/window_phase_memory.py <w>/experiments/<run> <w> 24
```

The numbers above are in `docs/reviews/gate-a/measurements.json`.
