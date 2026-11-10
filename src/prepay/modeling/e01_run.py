"""E01 orchestration (ADR 0014 §9): one child process per job, preflight, budget and a ledger.

``prepay experiment e01 run --stage pilot|folds|stability|all`` runs a stage's jobs in order.
Each job is a fresh ``prepay`` child process. Its peak memory is then its own, and no job runs
code from before a change (R2 defect 15). Before each job the orchestrator:

1. stops if the ``STOP`` file exists;
2. waits until the host has the required free commit (the preflight), or stops after a limit;
3. for a fold after the pilot, projects its peak conservatively from the pilot, and stops if
   the projection exceeds the budget.

After each job it records the child's resource report and stops on a failure or on a peak above
the budget. After the pilot fold it compares model-file digests with the V1 run of the same
origin. A mismatch stops the queue, and the later folds run only after the owner records a
written waiver. Nothing is waived silently (E01-D5).

The ledger (``ledger.json``) holds **metadata only**: job names, times, exit codes, memory,
projections, digests-based identity booleans and differing file names. It holds no metric,
count or result, so it can be shared with the agent (ADR 0014 §9.6).

Real-data safeguards: the stage ``all`` is refused, so the owner reviews the pilot before the
other folds; the preflight can't be lowered below 12 GiB or the budget raised above 10 GiB; the
pilot needs ``--reproduce-against``; and outputs can't be written inside the repository except
under the ignored ``artifacts/``.
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

from prepay import periods
from prepay.features.panel import sample_clause
from prepay.ingest.lock import DataLock, read_lock
from prepay.io import read_json, write_json_atomic
from prepay.modeling.e01 import (
    ADR,
    EXPERIMENT,
    S1,
    E01Error,
    Overrides,
    fold_config,
    folds_dir,
    write_summary,
)
from prepay.modeling.experiment import find_run
from prepay.modeling.registry import MANIFEST
from prepay.provenance import REPO_ROOT, git_sha
from prepay.resources import free_commit_bytes, job_peak_bytes

GIB = 2**30
MIN_FREE_COMMIT = 12 * GIB  # E01-D4
BUDGET = 10 * GIB  # E01-D4
PREFLIGHT_WAIT_SECONDS = 2 * 3600
PREFLIGHT_POLL_SECONDS = 60
LEDGER = "ledger.json"
STOP = "STOP"
JOBS = "jobs"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_PREFLIGHT = 3
EXIT_BUDGET = 4
EXIT_REPRODUCTION = 5
EXIT_STOPPED = 6
EXIT_PROJECTION = 7
STAGES = ("pilot", "folds", "stability", "all")


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


# --------------------------------------------------------------------------- ledger
def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def load_ledger(root: Path, lock: DataLock) -> dict[str, Any]:
    path = root / LEDGER
    if path.is_file():
        ledger = read_json(path)
        if ledger["data_lock_fingerprint"] != lock.fingerprint():
            raise E01Error("this E01 directory belongs to a different data lock")
        return dict(ledger)
    return {
        "kind": "prepay-e01-ledger",
        "experiment": EXPERIMENT,
        "adr": ADR,
        "note": "metadata only: times, exit codes, memory, projections and identity booleans",
        "synthetic": lock.synthetic,
        "data_lock_fingerprint": lock.fingerprint(),
        "created_utc": _now(),
        "waiver": None,
        "runs": [],
        "jobs": [],
    }


def save_ledger(root: Path, ledger: dict[str, Any]) -> None:
    write_json_atomic(root / LEDGER, ledger)


def _pilot_record(ledger: dict[str, Any], origin: str) -> dict[str, Any] | None:
    """The latest pilot job that ran to completion (passed, or stopped on an identity mismatch)."""
    found = [
        j
        for j in ledger["jobs"]
        if j["job"] == f"fold {origin}" and j["outcome"] in ("ok", "reproduction_mismatch")
    ]
    return found[-1] if found else None


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
    """Conservative projection (ADR 0014 §9.3): everything above the pilot's starting commit is
    scaled by the largest row ratio. Whole-job peaks only; stage figures are never used."""
    start = int(pilot.get("start_commit_bytes") or 0)
    peak = int(pilot["job_peak_bytes"])
    ratios = [f / p for f, p in zip(fold_rows, pilot_rows, strict=True) if p > 0]
    scale = max([1.0, *ratios])
    return int(start + (peak - start) * scale)


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


def _preflight(
    options: Options, free_commit: Callable[[], int | None], sleep: Callable[[float], None]
) -> tuple[bool, int | None]:
    waited = 0.0
    while True:
        free = free_commit()
        if free is None or free >= options.min_free_commit_bytes:
            return True, free
        if waited >= options.preflight_wait_seconds:
            return False, free
        sleep(options.preflight_poll_seconds)
        waited += options.preflight_poll_seconds


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
    (root / JOBS).mkdir(exist_ok=True)
    ledger = load_ledger(root, lock)
    if options.waiver:
        ledger["waiver"] = {"text": options.waiver, "recorded_utc": _now()}
    ledger["runs"].append(
        {
            "stage": options.stage,
            "started_utc": _now(),
            "git_sha": git_sha(),
            "min_free_commit_bytes": options.min_free_commit_bytes,
            "budget_bytes": options.budget_bytes,
        }
    )
    save_ledger(root, ledger)
    pilot_origin = overrides.origins[0]
    jobs = plan(options.stage, overrides)
    if options.stage == "folds":
        pilot = _pilot_record(ledger, pilot_origin)
        if pilot is None:
            raise E01Error(f"run the pilot (fold {pilot_origin}) first")
        check = pilot.get("reproduction")
        if pilot["outcome"] == "reproduction_mismatch" and ledger["waiver"] is None:
            raise E01Error(
                "the pilot's model files differ from the V1 run; investigate, then record a "
                "written --waive-reproduction-mismatch to continue (E01-D5)"
            )
        if check is None and not lock.synthetic:
            raise E01Error("the pilot has no reproduction record (E01-D5)")
    pilot_rows: tuple[int, int] | None = None
    for job in jobs:
        record: dict[str, Any] = {"job": job.name, "started_utc": _now()}
        code = _run_job(
            job, options, lock, overrides, ledger, record, pilot_origin, spawn, free_commit, sleep
        )
        if pilot_rows is None and job.kind == "fold" and job.arg != pilot_origin:
            pilot_rows = record.pop("_pilot_rows", None)
        record["finished_utc"] = _now()
        ledger["jobs"].append(record)
        save_ledger(root, ledger)
        if code != EXIT_OK:
            return code
    write_summary(root, origins=overrides.origins, ledger=ledger)
    ledger["jobs"].append({"job": "summary", "finished_utc": _now(), "outcome": "ok"})
    save_ledger(root, ledger)
    return EXIT_OK


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
    if (options.root / STOP).exists():
        record["outcome"] = "stopped_by_file"
        return EXIT_STOPPED
    ok, free = _preflight(options, free_commit, sleep)
    record["free_commit_before_bytes"] = free
    if not ok:
        record["outcome"] = "preflight_failed"
        return EXIT_PREFLIGHT
    if job.kind == "fold" and job.arg != pilot_origin:
        pilot = _pilot_record(ledger, pilot_origin)
        if pilot is not None and "job_peak_bytes" in pilot:
            pilot_rows = _row_counts(options.data_root, pilot_origin, overrides)
            fold_rows = _row_counts(options.data_root, job.arg, overrides)
            projection = projected_peak(pilot, pilot_rows, fold_rows)
            record["projected_peak_bytes"] = projection
            if projection > options.budget_bytes and not options.accept_projection:
                record["outcome"] = "projection_above_budget"
                return EXIT_PROJECTION
    report_path = options.root / JOBS / f"{job.kind}-{job.arg}.resource.json"
    report_path.unlink(missing_ok=True)
    started = time.perf_counter()
    code = spawn(_child_args(job, options), report_path)
    record["exit_code"] = code
    record["seconds"] = round(time.perf_counter() - started, 1)
    resources: dict[str, Any] = read_json(report_path) if report_path.is_file() else {}
    for key in ("peak_commit_bytes", "peak_rss_bytes", "start_commit_bytes"):
        record[key] = resources.get(key)
    record["job_peak_bytes"] = job_peak_bytes(resources) if resources else None
    record["within_budget"] = (
        record["job_peak_bytes"] is not None and record["job_peak_bytes"] <= options.budget_bytes
    )
    if code != 0:
        record["outcome"] = "failed"
        return EXIT_FAILED
    if not record["within_budget"]:
        record["outcome"] = "over_budget"
        return EXIT_BUDGET
    if job.kind == "fold" and job.arg == pilot_origin and options.reproduce_against is not None:
        e01_run = find_run(folds_dir(options.root), lock, fold_config(job.arg, overrides))
        if e01_run is None:
            raise E01Error("the pilot finished but its run directory is missing")
        check = reproduction(e01_run, options.reproduce_against, job.arg, lock)
        record["reproduction"] = check
        record["run_id"] = e01_run.name
        if not check["identical"] and ledger["waiver"] is None:
            record["outcome"] = "reproduction_mismatch"
            return EXIT_REPRODUCTION
    record["outcome"] = "ok"
    return EXIT_OK


def origin_month(origin: str) -> int:
    return periods.parse_iso(origin)
