"""E01 orchestration (ADR 0014 §9): one child process per job, preflight, budget and a ledger.

``prepay experiment e01 run --stage pilot|folds|stability|all`` runs a stage's jobs in order.
Each job is a fresh ``prepay`` child process. Its peak memory is then its own, and no job runs
code from before a change (R2 defect 15). Before each child, including the verification child,
the orchestrator:

1. stops if the ``STOP`` file exists;
2. waits until the host has the required free commit (the preflight), or stops after a limit.
   On real data a host that gives no reading fails the preflight;
3. for a fold after the pilot, projects its peak conservatively from the pilot, and stops if
   the projection exceeds the budget.

After each child it records the child's resource report and stops on a failure, on a missing
measurement, or on a peak above the budget. **The budget is checked when the child exits:** no
hard process limit is set, so a job above the budget stops the queue but isn't prevented from
reaching that peak. The preflight and the projection are what keep a job from starting into one.

After each fold it runs ``prepay experiment verify --unsealed`` as another child. The fold stops
the queue unless the verifier exits 0 and writes a well-formed report for that run that holds
every mandatory check and no failed one (synthetic data exempts ``clean_code`` only). Only the
names of failed checks reach the ledger. After the pilot fold it also compares model-file
digests with the V1 run of the same origin. A mismatch stops the queue, and the later folds run
only after the owner records a written waiver. Nothing is waived silently (E01-D5).

**One execution identity per E01 directory** (Gate B review, 2026-11-10): the Git commit, the
dependency lock, the data lock, the feature definitions and the whole E01 configuration. The
ledger records it at the first stage. Every later stage, every job, and every run it produces
must match it, so the pilot, the folds and S1 can't mix revisions. A change starts a new
directory and a new pilot. The folds need this identity's pilot, and S1 needs its folds.

The ledger (``ledger.json``) holds **metadata only**: job names, times, exit codes, memory,
projections, identity digests and booleans, and differing file and check names. It holds no
metric, count or result, so it can be shared with the agent (ADR 0014 §9.6).

Only one orchestrator may run on a directory at a time: it holds ``.e01-run.lock`` for the whole
stage, and a second run is refused.

Real-data safeguards: the stage ``all`` is refused, so the owner reviews the pilot before the
other folds; the preflight can't be lowered below 12 GiB or the budget raised above 10 GiB; the
pilot needs ``--reproduce-against``; the worktree must be clean at a known commit; and outputs
can't be written inside the repository except under the ignored ``artifacts/``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from prepay.features.panel import sample_clause
from prepay.ingest.lock import DataLock, read_lock
from prepay.io import read_json, write_json_atomic
from prepay.modeling.e01 import (
    ADR,
    EXPERIMENT,
    IDENTITY_FIELDS,
    S1,
    E01Error,
    Overrides,
    execution_identity,
    fold_config,
    folds_dir,
    identity_digest,
    identity_mismatches,
    stability_dir,
    write_summary,
)
from prepay.modeling.experiment import find_run
from prepay.modeling.registry import MANIFEST
from prepay.modeling.verify import required_checks
from prepay.provenance import REPO_ROOT, git_dirty, git_sha
from prepay.resources import free_commit_bytes, job_peak_bytes

GIB = 2**30
MIN_FREE_COMMIT = 12 * GIB  # E01-D4
BUDGET = 10 * GIB  # E01-D4
PREFLIGHT_WAIT_SECONDS = 2 * 3600
PREFLIGHT_POLL_SECONDS = 60
LEDGER = "ledger.json"
STOP = "STOP"
#: Held for a whole ``e01 run``; a second orchestrator on the same directory is refused.
RUN_LOCK = ".e01-run.lock"
JOBS = "jobs"
#: How the budget is enforced, recorded with every stage run.
BUDGET_CHECK = "checked when each child exits; no hard process limit"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PREFLIGHT = 3
EXIT_BUDGET = 4
EXIT_REPRODUCTION = 5
EXIT_STOPPED = 6
EXIT_PROJECTION = 7
EXIT_VERIFY = 8
EXIT_IDENTITY = 9
#: Verification checks that don't gate a synthetic run: tests and dry runs may use a working
#: tree with edits. Real data never gets that far with a dirty tree (check_options refuses it).
SYNTHETIC_NON_GATING = ("clean_code",)
STAGES = ("pilot", "folds", "stability", "all")
RESOURCE_KEYS = (
    "peak_commit_bytes",
    "peak_rss_bytes",
    "start_commit_bytes",
    "baseline_commit_bytes",
)


@dataclass(frozen=True)
class Job:
    kind: str  # "fold" or "stability"
    arg: str  # origin or stability kind

    @property
    def name(self) -> str:
        return f"{self.kind} {self.arg}"


@dataclass(frozen=True)
class Options:
    data_root: Path
    lock_path: Path
    root: Path
    stage: str
    min_free_commit_bytes: int = MIN_FREE_COMMIT
    budget_bytes: int = BUDGET
    preflight_wait_seconds: float = PREFLIGHT_WAIT_SECONDS
    preflight_poll_seconds: float = PREFLIGHT_POLL_SECONDS
    reproduce_against: Path | None = None
    waiver: str | None = None
    accept_projection: bool = False
    overrides: dict[str, Any] = field(default_factory=dict)
    log_level: str = "WARNING"


def plan(stage: str, overrides: Overrides) -> list[Job]:
    """Jobs of a stage. The pilot is the first declared origin (2007-12 for real data)."""
    origins = overrides.origins
    pilot = [Job("fold", origins[0])]
    folds = [Job("fold", o) for o in origins[1:]]
    stability = [Job("stability", kind) for kind in S1]
    if stage == "pilot":
        return pilot
    if stage == "folds":
        return folds
    if stage == "stability":
        return stability
    if stage == "all":
        return pilot + folds + stability
    raise E01Error(f"stage must be one of {STAGES}")


def check_options(options: Options, lock: DataLock, overrides: Overrides) -> None:
    """Refuse settings that ADR 0014 doesn't allow for real data."""
    overrides.check(lock)
    if options.stage not in STAGES:
        raise E01Error(f"stage must be one of {STAGES}")
    if lock.synthetic:
        return
    if options.stage == "all":
        raise E01Error("real data: run the pilot, have it reviewed, then the other stages")
    if options.min_free_commit_bytes < MIN_FREE_COMMIT:
        raise E01Error("real data: the preflight can't be lowered below 12 GiB (E01-D4)")
    if options.budget_bytes > BUDGET:
        raise E01Error("real data: the budget can't be raised above 10 GiB (E01-D4)")
    if options.stage == "pilot" and options.reproduce_against is None:
        raise E01Error("real data: the pilot needs --reproduce-against <V1 run> (E01-D5)")
    root = options.root.resolve()
    if root.is_relative_to(REPO_ROOT) and not root.is_relative_to(REPO_ROOT / "artifacts"):
        raise E01Error("real data: write E01 outputs outside the repository or under artifacts/")
    if git_sha() is None or git_dirty() is not False:
        raise E01Error("real data: run from a clean Git worktree at a known commit")


# --------------------------------------------------------------------------- run lock
def acquire_run_lock(root: Path, stage: str) -> Path:
    """Create the run lock exclusively, or refuse if another run holds it.

    Gate B's dry run showed why: stopping a shell on Windows leaves its child processes running,
    and two orchestrators then wrote jobs and the ledger in the same directory. A lock left by a
    crash is never removed automatically; the owner checks that no E01 process is running, then
    deletes it.
    """
    import json

    path = root / RUN_LOCK
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        holder = path.read_text(encoding="utf-8", errors="replace").strip()
        raise E01Error(
            f"another E01 run holds {path} ({holder}). If no E01 process is running, delete the "
            "file and run again."
        ) from None
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        out.write(json.dumps({"pid": os.getpid(), "stage": stage, "started_utc": _now()}))
    return path


# --------------------------------------------------------------------------- ledger
def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def load_ledger(root: Path, lock: DataLock, identity: dict[str, Any]) -> dict[str, Any]:
    """This directory's ledger, or a new one bound to ``identity``; another identity is refused."""
    path = root / LEDGER
    if path.is_file():
        ledger = dict(read_json(path))
        if ledger["data_lock_fingerprint"] != lock.fingerprint():
            raise E01Error("this E01 directory belongs to a different data lock")
        if "identity" not in ledger:
            raise E01Error(
                "this E01 directory has no execution identity (made before the Gate B review); "
                "start a new E01 directory"
            )
        differing = identity_drift(ledger, identity)
        if differing:
            raise E01Error(
                f"this E01 directory was started under a different {', '.join(differing)}. Runs "
                "of different revisions are never mixed: start a new E01 directory and run the "
                "pilot again"
            )
        return ledger
    return {
        "kind": "prepay-e01-ledger",
        "experiment": EXPERIMENT,
        "adr": ADR,
        "note": "metadata only: times, exit codes, memory, projections and identity booleans",
        "synthetic": lock.synthetic,
        "data_lock_fingerprint": lock.fingerprint(),
        "identity": identity,
        "identity_digest": identity_digest(identity),
        "created_utc": _now(),
        "waiver": None,
        "runs": [],
        "jobs": [],
    }


def save_ledger(root: Path, ledger: dict[str, Any]) -> None:
    write_json_atomic(root / LEDGER, ledger)


def identity_drift(ledger: dict[str, Any], identity: dict[str, Any]) -> list[str]:
    """The identity fields in which ``identity`` differs from the one the ledger is bound to."""
    recorded = ledger["identity"]
    return [k for k in IDENTITY_FIELDS if recorded.get(k) != identity.get(k)]


def _record(ledger: dict[str, Any], job: str, outcomes: tuple[str, ...]) -> dict[str, Any] | None:
    """The latest record of ``job`` under the ledger's execution identity with one of ``outcomes``.

    Records of another identity are never accepted, even if a ledger was edited or merged.
    """
    found = [
        j
        for j in ledger["jobs"]
        if j["job"] == job
        and j["outcome"] in outcomes
        and j.get("identity_digest") == ledger["identity_digest"]
    ]
    return found[-1] if found else None


def _pilot_record(ledger: dict[str, Any], origin: str) -> dict[str, Any] | None:
    """The latest pilot job that ran to completion (passed, or stopped on an identity mismatch)."""
    return _record(ledger, f"fold {origin}", ("ok", "reproduction_mismatch"))


def _check_recorded_run(root: Path, record: dict[str, Any], identity: dict[str, Any]) -> None:
    """The run a ledger record names still exists and was made under ``identity``."""
    run_dir = folds_dir(root) / str(record.get("run_id"))
    if not (run_dir / MANIFEST).is_file():
        raise E01Error(f"the run of {record['job']} named by the ledger is missing")
    differing = identity_mismatches(read_json(run_dir / MANIFEST), identity)
    if differing:
        raise E01Error(f"the run of {record['job']} was made under a different {differing}")


def check_prerequisites(
    stage: str, ledger: dict[str, Any], lock: DataLock, overrides: Overrides, root: Path
) -> None:
    """The folds need this identity's pilot, and S1 needs this identity's folds too."""
    if stage not in ("folds", "stability"):
        return
    origin = overrides.origins[0]
    pilot = _pilot_record(ledger, origin)
    if pilot is None:
        raise E01Error(f"run the pilot (fold {origin}) of this execution identity first")
    if pilot["outcome"] == "reproduction_mismatch" and ledger["waiver"] is None:
        raise E01Error(
            "the pilot's model files differ from the V1 run; investigate, then record a "
            "written --waive-reproduction-mismatch to continue (E01-D5)"
        )
    if pilot.get("reproduction") is None and not lock.synthetic:
        raise E01Error("the pilot has no reproduction record (E01-D5)")
    _check_recorded_run(root, pilot, ledger["identity"])
    if stage == "stability":
        for other in overrides.origins[1:]:
            fold = _record(ledger, f"fold {other}", ("ok",))
            if fold is None:
                raise E01Error(
                    f"run the folds stage first: fold {other} of this identity is missing"
                )
            _check_recorded_run(root, fold, ledger["identity"])


# --------------------------------------------------------------------------- checks
def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def reproduction(e01_run: Path, v1_run: Path, origin: str, lock: DataLock) -> dict[str, Any]:
    """Byte identity of the V1 families' model files and preprocessor (E01-D5); digests only."""
    manifest = read_json(v1_run / MANIFEST)
    if manifest.get("experiment_id") != f"V1-{origin}":
        raise E01Error(f"{v1_run.name} is not the V1 run of {origin}")
    if manifest.get("data_lock_fingerprint") != lock.fingerprint():
        raise E01Error(f"{v1_run.name} was trained on a different data lock")
    names = sorted(p.relative_to(v1_run).as_posix() for p in (v1_run / "models").iterdir())
    names.append("preprocessor.json")
    differing = [n for n in names if _sha256(v1_run / n) != _sha256(e01_run / n)]
    return {
        "reference_run_id": manifest["run_id"],
        "compared_files": len(names),
        "identical": not differing,
        "differing_files": differing,
    }


def _row_counts(data_root: Path, origin: str, overrides: Overrides) -> tuple[int, int]:
    """Training rows (at the fold's sample) and evaluation rows of a fold: counts only."""
    from prepay.transform import warehouse_path

    config = fold_config(origin, overrides)
    windows = config.windows
    assert windows.evaluate is not None
    sample = sample_clause(config.train_sample_fraction, config.sample_index)
    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    try:
        train = con.execute(
            "select count(*) from fct_hazard_panel "  # noqa: S608 - fixed clause, bound months
            f"where target_month <= $last and {sample}",
            {"last": windows.train_last},
        ).fetchone()
        evaluate = con.execute(
            "select count(*) from fct_hazard_panel where target_month between $first and $last",
            {"first": windows.evaluate[0], "last": windows.evaluate[1]},
        ).fetchone()
    finally:
        con.close()
    return int(train[0] if train else 0), int(evaluate[0] if evaluate else 0)


def projected_peak(
    pilot: dict[str, Any], pilot_rows: tuple[int, int], fold_rows: tuple[int, int]
) -> int:
    """Conservative projection (ADR 0014 §9.3): everything above the pilot's baseline is scaled by
    the largest row ratio. Whole-job peaks only; stage figures are never used.

    The baseline is the job's commit after its libraries are imported and before it reads data
    (``baseline_commit_bytes``). Gate B's dry run showed why: measured from the command's start,
    about 1.4 GiB of library imports was scaled as if it grew with the data, and the gate stopped
    a fold projected at 10.2 GiB whose neighbours peaked under 1.9 GiB. Without a baseline (off
    Windows), the whole peak is scaled, which over-projects further.
    """
    start = int(pilot.get("baseline_commit_bytes") or pilot.get("start_commit_bytes") or 0)
    peak = int(pilot["job_peak_bytes"])
    ratios = [f / p for f, p in zip(fold_rows, pilot_rows, strict=True) if p > 0]
    scale = max([1.0, *ratios])
    return int(start + (peak - start) * scale)


def _measure(report: Path, budget: int, into: dict[str, Any]) -> None:
    """A child's resource figures, read after it exited, and the budget check on its peak.

    A missing or unreadable report, or one without a peak, leaves ``job_peak_bytes`` at ``None``
    and ``within_budget`` false: a budget that can't be confirmed doesn't pass.
    """
    try:
        loaded = read_json(report) if report.is_file() else {}
    except (OSError, ValueError):
        loaded = {}
    resources: dict[str, Any] = loaded if isinstance(loaded, dict) else {}
    for key in RESOURCE_KEYS:
        into[key] = resources.get(key)
    peak = job_peak_bytes(resources)
    into["job_peak_bytes"] = peak
    into["within_budget"] = peak is not None and peak <= budget


def _verification_report(out: Path, run_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    """The verifier's report if it is well formed and for ``run_dir``; else why not."""
    if not out.is_file():
        return None, "no_report"
    try:
        report = read_json(out)
    except (OSError, ValueError):
        return None, "invalid_report"
    if not _well_formed(report):
        return None, "invalid_report"
    if report["run_id"] != read_json(run_dir / MANIFEST).get("run_id"):
        return None, "report_for_another_run"
    return report, None


def _well_formed(report: Any) -> bool:
    if not isinstance(report, dict) or report.get("kind") != "prepay-run-verification":
        return False
    checks, failed = report.get("checks"), report.get("failed")
    if not isinstance(checks, dict) or not checks:
        return False
    if not all(isinstance(k, str) and isinstance(v, bool) for k, v in checks.items()):
        return False
    return (
        failed == sorted(k for k, ok in checks.items() if not ok)
        and report.get("all_pass") is (not failed)
        and report.get("seal_required") is False
    )


# --------------------------------------------------------------------------- run
Spawn = Callable[[list[str], Path], int]


def spawn_child(args: list[str], report: Path) -> int:
    """Run ``prepay <args>`` as a fresh process that writes its resource report to ``report``."""
    env = {**os.environ, "PREPAY_RESOURCE_REPORT": str(report)}
    command = [sys.executable, "-m", "prepay.cli", *args]
    return subprocess.run(command, env=env, check=False).returncode  # noqa: S603


def _child_args(job: Job, options: Options) -> list[str]:
    common = ["--data-root", str(options.data_root), "--lock", str(options.lock_path)]
    common += ["--out", str(options.root)]
    if options.overrides:
        import json

        common += ["--synthetic-overrides", json.dumps(options.overrides, sort_keys=True)]
    if job.kind == "fold":
        return [
            "--log-level",
            options.log_level,
            "experiment",
            "e01",
            "fold",
            "--origin",
            job.arg,
            *common,
        ]
    return [
        "--log-level",
        options.log_level,
        "experiment",
        "e01",
        "stability",
        "--kind",
        job.arg,
        *common,
    ]


def _free_commit_reading(free_commit: Callable[[], int | None]) -> int | None:
    try:
        value = free_commit()
    except OSError:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _preflight(
    options: Options,
    lock: DataLock,
    free_commit: Callable[[], int | None],
    sleep: Callable[[float], None],
) -> tuple[str, int | None]:
    """Wait for the free commit the job needs: ``ok``, ``failed`` after the wait limit, or
    ``stopped`` as soon as the STOP file appears (the wait can last hours).

    A host that gives no reading returns ``unavailable`` on real data: the gate can't be
    confirmed, so it fails closed. A synthetic run proceeds without one.
    """
    waited = 0.0
    while True:
        if (options.root / STOP).exists():
            return "stopped", None
        free = _free_commit_reading(free_commit)
        if free is None:
            return ("ok" if lock.synthetic else "unavailable"), None
        if free >= options.min_free_commit_bytes:
            return "ok", free
        if waited >= options.preflight_wait_seconds:
            return "failed", free
        sleep(options.preflight_poll_seconds)
        waited += options.preflight_poll_seconds


PREFLIGHT_OUTCOMES = {
    "stopped": (EXIT_STOPPED, "stopped_by_file"),
    "failed": (EXIT_PREFLIGHT, "preflight_failed"),
    "unavailable": (EXIT_PREFLIGHT, "preflight_unavailable"),
}


def _gate(
    options: Options,
    lock: DataLock,
    free_commit: Callable[[], int | None],
    sleep: Callable[[float], None],
    into: dict[str, Any],
) -> tuple[int, str] | None:
    """The STOP file and the preflight before every child; ``(exit, outcome)`` if it can't start."""
    if (options.root / STOP).exists():
        return EXIT_STOPPED, "stopped_by_file"
    state, free = _preflight(options, lock, free_commit, sleep)
    into["free_commit_before_bytes"] = free
    return PREFLIGHT_OUTCOMES.get(state)


def run(
    options: Options,
    *,
    spawn: Spawn = spawn_child,
    free_commit: Callable[[], int | None] = free_commit_bytes,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run one stage; returns an ``EXIT_*`` code. Every decision is written to the ledger."""
    lock = read_lock(options.lock_path)
    overrides = Overrides.from_json(options.overrides)
    check_options(options, lock, overrides)
    root = options.root
    root.mkdir(parents=True, exist_ok=True)
    lock_file = acquire_run_lock(root, options.stage)
    try:
        return _run_stage(options, lock, overrides, spawn, free_commit, sleep)
    finally:
        lock_file.unlink(missing_ok=True)


def _run_stage(
    options: Options,
    lock: DataLock,
    overrides: Overrides,
    spawn: Spawn,
    free_commit: Callable[[], int | None],
    sleep: Callable[[float], None],
) -> int:
    root = options.root
    (root / JOBS).mkdir(exist_ok=True)
    ledger = load_ledger(root, lock, execution_identity(lock, overrides))
    check_prerequisites(options.stage, ledger, lock, overrides, root)
    if options.waiver:
        ledger["waiver"] = {"text": options.waiver, "recorded_utc": _now()}
    ledger["runs"].append(
        {
            "stage": options.stage,
            "started_utc": _now(),
            "git_sha": ledger["identity"]["git_sha"],
            "identity_digest": ledger["identity_digest"],
            "min_free_commit_bytes": options.min_free_commit_bytes,
            "budget_bytes": options.budget_bytes,
            "budget_check": BUDGET_CHECK,
        }
    )
    save_ledger(root, ledger)
    pilot_origin = overrides.origins[0]
    for job in plan(options.stage, overrides):
        record: dict[str, Any] = {
            "job": job.name,
            "started_utc": _now(),
            "identity_digest": ledger["identity_digest"],
        }
        code = _run_job(
            job, options, lock, overrides, ledger, record, pilot_origin, spawn, free_commit, sleep
        )
        record["finished_utc"] = _now()
        ledger["jobs"].append(record)
        save_ledger(root, ledger)
        if code != EXIT_OK:
            return code
    write_summary(root, origins=overrides.origins, ledger=ledger)
    ledger["jobs"].append({"job": "summary", "finished_utc": _now(), "outcome": "ok"})
    save_ledger(root, ledger)
    return EXIT_OK


def _stop(record: dict[str, Any], code: int, outcome: str) -> int:
    record["outcome"] = outcome
    return code


def _run_job(
    job: Job,
    options: Options,
    lock: DataLock,
    overrides: Overrides,
    ledger: dict[str, Any],
    record: dict[str, Any],
    pilot_origin: str,
    spawn: Spawn,
    free_commit: Callable[[], int | None],
    sleep: Callable[[float], None],
) -> int:
    drift = identity_drift(ledger, execution_identity(lock, overrides))
    if drift:
        record["identity_mismatch"] = drift
        return _stop(record, EXIT_IDENTITY, "identity_changed")
    blocked = _gate(options, lock, free_commit, sleep, record)
    if blocked is not None:
        return _stop(record, *blocked)
    if job.kind == "fold" and job.arg != pilot_origin:
        pilot = _pilot_record(ledger, pilot_origin)
        if pilot is not None and pilot.get("job_peak_bytes") is not None:
            pilot_rows = _row_counts(options.data_root, pilot_origin, overrides)
            fold_rows = _row_counts(options.data_root, job.arg, overrides)
            projection = projected_peak(pilot, pilot_rows, fold_rows)
            record["projected_peak_bytes"] = projection
            if projection > options.budget_bytes and not options.accept_projection:
                return _stop(record, EXIT_PROJECTION, "projection_above_budget")
    report_path = options.root / JOBS / f"{job.kind}-{job.arg}.resource.json"
    report_path.unlink(missing_ok=True)
    started = time.perf_counter()
    code = spawn(_child_args(job, options), report_path)
    record["exit_code"] = code
    record["seconds"] = round(time.perf_counter() - started, 1)
    _measure(report_path, options.budget_bytes, record)
    if code != 0:
        return _stop(record, EXIT_FAILED, "failed")
    if record["job_peak_bytes"] is None:
        return _stop(record, EXIT_BUDGET, "budget_unverified")
    if not record["within_budget"]:
        return _stop(record, EXIT_BUDGET, "over_budget")
    drift = identity_drift(ledger, execution_identity(lock, overrides))
    if drift:
        record["identity_mismatch"] = drift
        return _stop(record, EXIT_IDENTITY, "identity_changed")
    if job.kind == "stability":
        base = stability_dir(options.root)
        runs = (
            sorted(p for p in base.iterdir() if (p / MANIFEST).is_file()) if base.is_dir() else []
        )
        for run_dir in runs:
            differing = identity_mismatches(read_json(run_dir / MANIFEST), ledger["identity"])
            if differing:
                record["identity_mismatch"] = differing
                return _stop(record, EXIT_IDENTITY, "identity_changed")
        return _stop(record, EXIT_OK, "ok")
    e01_run = find_run(folds_dir(options.root), lock, fold_config(job.arg, overrides))
    if e01_run is None:
        raise E01Error(f"fold {job.arg} finished but its run directory is missing")
    record["run_id"] = e01_run.name
    differing = identity_mismatches(read_json(e01_run / MANIFEST), ledger["identity"])
    if differing:
        record["identity_mismatch"] = differing
        return _stop(record, EXIT_IDENTITY, "identity_changed")
    verification: dict[str, Any] = {}
    record["verification"] = verification
    blocked = _gate(options, lock, free_commit, sleep, verification)
    if blocked is not None:
        return _stop(record, *blocked)
    _verify(e01_run, job, options, lock, overrides, spawn, verification)
    if verification["gating_failures"]:
        return _stop(record, EXIT_VERIFY, "verification_failed")
    if verification["job_peak_bytes"] is None:
        return _stop(record, EXIT_BUDGET, "budget_unverified")
    if not verification["within_budget"]:
        return _stop(record, EXIT_BUDGET, "over_budget")
    if job.arg == pilot_origin and options.reproduce_against is not None:
        check = reproduction(e01_run, options.reproduce_against, job.arg, lock)
        record["reproduction"] = check
        if not check["identical"] and ledger["waiver"] is None:
            return _stop(record, EXIT_REPRODUCTION, "reproduction_mismatch")
    return _stop(record, EXIT_OK, "ok")


def _verify(
    run_dir: Path,
    job: Job,
    options: Options,
    lock: DataLock,
    overrides: Overrides,
    spawn: Spawn,
    into: dict[str, Any],
) -> None:
    """``prepay experiment verify --unsealed`` in a child, measured like any job.

    Fills ``into`` with the exit code, the resource figures, the failed check names, and the
    ``gating_failures`` that stop the queue: a nonzero exit (``verifier_exit_nonzero``); a missing
    report (``no_report``), a malformed one (``invalid_report``) or one for another run
    (``report_for_another_run``); every failed check, except ``clean_code`` on synthetic data;
    and every mandatory check the report lacks (``missing:<name>``).
    """
    out = options.root / JOBS / f"verify-{job.arg}.json"
    resources = options.root / JOBS / f"verify-{job.arg}.resource.json"
    out.unlink(missing_ok=True)
    resources.unlink(missing_ok=True)
    args = [
        "--log-level",
        options.log_level,
        "experiment",
        "verify",
        "--run",
        str(run_dir),
        "--data-root",
        str(options.data_root),
        "--lock",
        str(options.lock_path),
        "--out",
        str(out),
        "--unsealed",
    ]
    if lock.synthetic:
        args.append("--synthetic-allow-dirty")
    started = time.perf_counter()
    code = spawn(args, resources)
    into["exit_code"] = code
    into["seconds"] = round(time.perf_counter() - started, 1)
    _measure(resources, options.budget_bytes, into)
    report, problem = _verification_report(out, run_dir)
    failed = [str(name) for name in report["failed"]] if report else []
    exempt = SYNTHETIC_NON_GATING if lock.synthetic else ()
    gating = [] if code == 0 else ["verifier_exit_nonzero"]
    if problem is not None:
        gating.append(problem)
    gating += [name for name in failed if name not in exempt]
    if report is not None:
        mandatory = required_checks(fold_config(job.arg, overrides).models)
        gating += [f"missing:{name}" for name in sorted(mandatory - set(report["checks"]))]
    into["failed_checks"] = failed
    into["gating_failures"] = gating
