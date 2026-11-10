# Prepay 2.0 Gate B: E01 engineering and the synthetic dry run

Prepared 2026-11-10 by the implementing agent, for the owner's review. **Self-review, not
independent review.** Everything here ran on synthetic data. **No private real-data job was
launched.** Gate C, the owner-run pilot, waits for the owner's approval.

## Verdict

**Gate B is complete and ready for review.** Each item of ADR 0014 §9.2 is built, tested in
CI and exercised end to end on synthetic data, with the exact staged commands the owner would
run.

| Item (ADR 0014 §9.2) | Result | Evidence |
|---|---|---|
| B1: B0 in the folds | Done. Every E01 fold fits all eight families | `fold_config`; the fold-report test checks the model list |
| B2: effect sizes and uncertainty | Done: one two-way bootstrap per fold for every statistic; Bonferroni-simultaneous Wald intervals in three families; classes; A/E and regime-cell intervals; month-block CPR interval | `prepay.evaluation.simultaneous`; 13 unit tests, including equality with `inference.two_way` |
| B3: D2 probes and D3 support per fold | Done; D3 by rows and by balance | Fold report `probes` and `support` |
| B4: summary and the owner's local report | Done. R1–R7 are computed fields, and the Markdown report is deterministic | `prepay.modeling.e01`, `e01_report`; determinism test |
| B5: resume and provenance | Done. Exact-provenance reuse; mismatched or interrupted runs refused; real data needs a clean tree | `find_run`, `find_or_run`; resume and refusal tests |
| B6: orchestration | Done. One child process per job; 12 GiB preflight, 10 GiB budget, STOP file, conservative projection, byte-identity pilot, `verify --unsealed` after every fold, metadata-only ledger | `prepay.modeling.e01_run`; stop-condition tests |
| B7: exact synthetic dry run; CI green | Done. The final attempt at `398ce76` ran the pilot, all six folds and the S1 sample job. Its S1 seed job was held by the preflight on a busy host and stopped with `STOP`; it completed in attempt 4 at `067edd0` | §5 below, `docs/reviews/gate-b/` (ledgers, script, synthetic report); CI green on every commit, last [42858617718](https://github.com/s2002kumar/PrePay/actions/runs/42858617718) (`398ce76`) |

## 1. What the owner gets

- **One command per stage:** `prepay experiment e01 run --stage pilot|folds|stability`. Each job
  is a fresh process, and the command resumes after any stop. The runbook (§10) gives the
  exact commands.
- **A local report.** `e01-report.md` states, in fixed wording, what the reading rules found:
  - R7 nominations, or "no development evidence for a change";
  - R2 consistency against M1 and against B2;
  - R3 for each design bundle, with what the bundle differs in;
  - calibration transfer, financial materiality and stability;
  - tables of every classified comparison and every fold.

  Every page carries the development-evidence label and a private banner on real data.
- **A metadata-only ledger** (`ledger.json`), which is all the agent reads. It holds job names,
  times, exit codes, memory, projections, the names of failed implementation checks, and the
  pilot's byte-identity result. It holds no metric, count or result.

## 2. Statistical design as built (ADR 0014 §6–§7)

- **One pass of two-way replicates per fold.** Each replicate draws loan and month
  multiplicities exactly as `inference.two_way` does. One weight vector then gives, for every
  model:
  - the mean log loss;
  - the payoff A/E, overall and in the bottom and top fifths;
  - the payoff A/E per regime cell.

  Any paired difference's draw is a difference of draws. A unit test shows it equals
  `two_way`'s own draw for the same seed, to 1e-10.
- **Families and classes.**
  - F-M1, F-B2 and F-DESIGN each have m = 5 × 6 = 30 comparisons, so z = 3.144.
  - The simultaneous interval is estimate ± z × the bootstrap SE.
  - The classes are `lower_loss`, `higher_loss`, `non_inferior` (upper limit below 0.5% of the
    reference's log loss) and `inconclusive`. A test keeps "non-inferior" apart from "not
    significant".
- **Rules as fields.**
  - R2 and R3 count classes on the four regime-shift folds and check the controls.
  - R3 names each bundle's differences. Only X2 − X1 is marked as a single choice.
  - R4 checks every regime cell with ≥ 50 payoffs.
  - R5 reads the T3/T4 checks of the forward study's own `_verdicts`, read-only.
  - R6 reports only measured SDs: seedless convex fits get 0, unmeasured families "not
    measured", and nothing is imputed.
  - R7 requires R2 vs M1, never higher loss than B2, and no blocking D2 flag. The tail flag is
    informational, as in ADR 0009.

## 3. Safeguards

| Risk | Safeguard | Test |
|---|---|---|
| Reusing a run made by other code or settings | Reuse needs equal experiment ID, config digest, lock, Git SHA, software-lock, feature and derived-feature digests. Anything else is refused | `test_runs_with_other_provenance_or_interrupted_runs_are_refused` |
| A half-written run directory | A directory without a manifest is refused, never repaired | same |
| Real data from edited code | Real-data runs need a clean worktree with a known commit | `find_or_run` |
| Skipping the owner's review after the pilot | Real data refuses the `all` stage. The folds wait for a pilot record | `test_real_data_refuses_overrides_and_loosened_safeguards` |
| Loosened memory gates | Real data refuses a preflight below 12 GiB or a budget above 10 GiB | same |
| A silent identity waiver | A pilot mismatch stops with exit 5. The folds run only with a written `--waive-reproduction-mismatch`, kept in the ledger and the summary | `test_orchestrator_stops_on_stop_file_preflight_budget_and_mismatch` |
| A broken model invariant | `verify --unsealed` after every fold stops with exit 8 | same |
| Real outputs in the repository | Real data refuses an output directory inside the repository unless it is under the ignored `artifacts/` | real-data refusal test |
| Leaking results to the agent | The ledger's keys are allow-listed by a test | `test_ledger_holds_metadata_only` |
| Opened or forward months | The fold job reads outcome months ≤ 2019-12 only (reader spy). Nothing in E01 imports or writes the forward study's state | `test_a_trained_fold_without_evaluation_is_evaluated_not_retrained` |
| A STOP that can't interrupt a long wait | The STOP file is checked at every preflight poll | stop-condition test, and the final dry run (ended a 23-minute wait in 20 s) |
| Two orchestrators on one directory | `.e01-run.lock`, created exclusively for the whole stage and released on every exit. A second run is refused with the holder's pid and start time | `test_only_one_orchestrator_runs_on_a_directory` |

## 4. Found during Gate B: orphaned processes on Windows

The first two dry-run attempts exposed a real hazard.

**What happened.**
- I stopped the first attempt from the agent's task controls, because I needed to change code.
  That killed only the outer shell. On Windows the script and its children kept running, and the
  script went on into the pilot, folds and stability stages.
- A second attempt then ran on the same directory. For a few minutes two orchestrators launched
  jobs and wrote the ledger there.
- The second attempt's pilot found the first attempt's half-written fold directory, which had no
  manifest. It refused to use it, which was correct.

**What I did.**
- I killed every dry-run process tree.
- I added `.e01-run.lock`, so a second orchestrator is always refused, with a test.
- I documented the safe way to stop E01: the `STOP` file, or killing the whole tree.
- The run reported below is a fresh third attempt on a clean directory.

**Owner implication.** Don't close the terminal to stop E01. Create `<out>/STOP`, which stops
the queue before the next job, or end the whole process tree.

## 5. The exact synthetic dry run

The dry run follows the owner's staged procedure (runbook §10) on the synthetic dev world:
2,000 fictional loans per vintage, 2003–2026, fraction 0.1, every ADR 0014 setting.

**The setup:**
- The V1 reference for the pilot is a fold 2007-12 trained by the V1 path at `7b2a11b`. The E01
  pilot was trained at the final commit, so the identity check crosses commits, as the real
  pilot's will (`dbcfb1d` to the E01 commit).
- The only deviation from the real commands is the preflight, lowered to 4 GiB, which only
  synthetic data allows. This laptop never had 12 GiB free.
- First, the unchanged command showed that the approved 12 GiB preflight refuses to start on
  this host (exit 3).

**Final run, commit `398ce76`, clean tree, kept awake:**

| Job | Outcome | Time | Peak commit | Baseline | Projected peak | Free commit before | Implementation checks | Pilot byte identity |
|---|---|---:|---:|---:|---:|---:|---|---|
| fold 2007-12 | preflight failed (the approved 12 GiB; exit 3) | — | — | — | — | 6.78 GiB | — | — |
| fold 2007-12 | ok | 302 s | 1.86 GiB | 1.42 GiB | — | 6.43 GiB | none failed | identical (15 files) |
| fold 2009-12 | ok | 354 s | 1.88 GiB | 1.42 GiB | 2.72 GiB | 7.53 GiB | none failed | — |
| fold 2011-12 | ok | 321 s | 1.89 GiB | 1.42 GiB | 3.82 GiB | 7.04 GiB | none failed | — |
| fold 2013-12 | ok | 378 s | 1.93 GiB | 1.42 GiB | 4.88 GiB | 7.04 GiB | none failed | — |
| fold 2015-12 | ok | 595 s | 1.95 GiB | 1.42 GiB | 6.01 GiB | 7.56 GiB | none failed | — |
| fold 2017-12 | ok | 677 s | 1.93 GiB | 1.42 GiB | 7.43 GiB | 5.02 GiB | none failed | — |
| stability samples | ok | 1853 s | 2.06 GiB | 1.42 GiB | — | 5.53 GiB | — | — |
| stability seeds | stopped by STOP during the preflight wait (exit 6) | — | — | — | — | — | — | — |

**How to read the table:**
- Every job stayed far under the 10 GiB budget.
- The conservative projections (2.7–7.4 GiB) stayed above the measured peaks (1.86–1.95 GiB),
  as intended.
- Implementation checks passed after every fold.
- The pilot's 15 model and preprocessor files are byte-identical to the V1 run made at another
  commit.

**The S1 seed job did not run in this final attempt.**
- Other applications took the host's free commit down to 1.0–2.2 GiB (the WSL virtual machine
  alone held about 3.7 GB). The seed job's preflight therefore waited, as designed.
- After 23 minutes I created the `STOP` file. It ended the wait within 20 seconds, recorded
  `stopped_by_file` and released the run lock, which exercised the fix of `398ce76` on a real
  wait.
- The seed job ran to completion in attempt 4 (`067edd0`): exit 0, 245 s, 1.93 GiB peak. The
  stability code is the same in both commits; only the orchestrator's preflight changed.
- The final summary therefore reports `complete: false`, with the samples kind finished and the
  seeds kind not.

**Wall times** were measured on the owner's laptop, shared with other work, with the dev world
at 1/25 of the real sample. They are not estimates for real data.

**Earlier attempts, and what each found.** Each defect was fixed and tested before the next
attempt:

| Attempt | Code | Outcome | Finding and fix |
|---|---|---|---|
| 1–2 | `d0c8aae`, `7b2a11b` | stopped by me | Orphaned processes on Windows (§4) led to the run lock (`2d8fa06`) |
| 3 | `2d8fa06` | the folds stage stopped at fold 2011-12 (exit 7) | The projection scaled about 1.4 GiB of library imports with the data: 5.49 and 10.15 GiB projected against at most 1.88 GiB measured. The fix is a post-import baseline (`067edd0`) |
| 4 | `067edd0` | complete: 6 folds and S1, all exit 0 | Fold 2015-12's wall time (12.7 h) includes 12.5 h of Modern Standby (Windows System log: standby 20:38–09:10 local); about 13 min active. The job survived standby |
| — | `067edd0` | private runner test | The runner's E01 queue worked end to end from a fresh worktree. The 12 GiB preflight then waited, and the STOP file couldn't interrupt that wait. Fixed in `398ce76`. Rerun from `398ce76`, the runner refused to reuse folds made by `067edd0` (`ProvenanceError`), as designed |
| — | `398ce76` | review of the dry-run outputs | On Windows the local report was written with CRLF line endings (60 in an empty-directory report), so its bytes differed from a Linux run. It is now written with LF, as the rest of the repository's writers are; a test that needs no training checks the bytes. No number or wording changes |

**Numerical neutrality of the refactor.** I evaluated the synthetic V1 fold 2009-12 of Gate A
with `main` before Gate B (`18c94a7`) and with `067edd0`. All **2,586** reported values are
bit-identical. The comparison excludes only the stage memory labels.

## 6. What the dry run doesn't show

- **Real-scale memory and time.** The synthetic dev world has 2,000 loans per vintage, against
  about 50,000 in the real sample. The real pilot measures both before any other fold runs,
  under the 10 GiB budget.
- **Anything about real model accuracy.** The synthetic truth is a multinomial logit without
  regime effects, so the rule results in the dry run say nothing about real mortgages.
- **The private runner wrapper on real data.** It gained an E01 queue that copies only the
  ledger, and it hasn't run on real data.

## 7. Changes to existing code

| Change | Why no reported number changes |
|---|---|
| `evaluate_development` split into `evaluate_fold` plus a wrapper | Same computations in the same order. The V1 tests pass unchanged except for the renamed stage memory fields |
| Stage fields renamed to `process_peak_rss_bytes` / `process_peak_commit_bytes`, plus `commit_now_bytes` | Labels only (ADR 0014 revision 4) |
| `run_experiment(evaluate=..., save_support=...)` | Both default to the old behavior. `support.json` is written only for E01 folds and changes no model file |
| `stability(runner=..., experiment_prefix=...)` | Both default to the old behavior |
| `verify_run(require_seal=...)` | Defaults to the old behavior. `--unsealed` exists for E01 only |
| Resource reports add `start_commit_bytes` | Measurement only |

`evaluation/forward.py`, the lockbox, the sealed runs and the registration are untouched.

## 8. Gate C: what the owner would run, and decide

- **Command.** One command, in the runbook §10: the pilot, fold 2007-12, with
  `--reproduce-against` the V1 run of 2026-11-03.
- **Host.** The pilot needs 12 GiB of free commit. This laptop had 9.9 GiB on 2026-11-09 during
  normal use, so heavy applications must be closed first.
- **What the agent sees afterwards:** the ledger. That is the exit code, time, peak commit,
  failed check names, and whether the model files are byte-identical.
- **What the owner reads:** `e01-report.md` for the pilot's fold, if wanted.
- **Host preparation.**
  - Close heavy applications. On 2026-11-10 the WSL virtual machine alone held about 3.7 GB,
    and free commit fell to 1–2 GiB.
  - Keep the machine from sleeping during the stage.
  - The orchestrator itself holds about 1.4 GiB, which the preflight already counts. It could
    be slimmed in a follow-up.
- **Decision.** If the pilot passes, the owner decides on Gate D: the other folds, then S1.
