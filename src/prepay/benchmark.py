"""Seeded, reproducible resource benchmark of the data pipeline on synthetic data.

Each stage runs in its own ``prepay`` subprocess, so peak RSS is attributable to that stage. The
child writes its own peak RSS and duration (``PREPAY_RESOURCE_REPORT``). Results include dataset
sizes, rows per second, host description and library versions. Numbers are measurements on one
machine, not guarantees.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

import duckdb

from prepay.io import read_json, write_json_atomic
from prepay.resources import host_description

PACKAGES = ("numpy", "pyarrow", "duckdb", "dbt-core", "dbt-duckdb")


def _run_stage(name: str, args: list[str], work_dir: Path) -> dict[str, Any]:
    report = work_dir / f".stage-{name}.json"
    report.unlink(missing_ok=True)
    env = {**os.environ, "PREPAY_RESOURCE_REPORT": str(report)}
    started = time.perf_counter()
    completed = subprocess.run(  # noqa: S603 - fixed argv built from our own CLI
        [sys.executable, "-m", "prepay.cli", "--log-level", "WARNING", *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    wall = time.perf_counter() - started
    if completed.returncode != 0:
        raise RuntimeError(f"benchmark stage {name} failed:\n{completed.stderr[-3000:]}")
    measured = read_json(report)
    report.unlink()
    return {
        "stage": name,
        "wall_seconds": round(wall, 2),
        "command_seconds": measured["seconds"],
        "peak_rss_mib": round(measured["peak_rss_bytes"] / 2**20, 1),
    }


def _dir_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _git_sha() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def run(preset: str, work_dir: Path, *, report_dir: Path) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    source = work_dir / "source"
    data = work_dir / "data"
    lock = work_dir / "data.lock.json"
    stages = [
        _run_stage("generate", ["synth", "--preset", preset, "--out", str(source)], work_dir),
        _run_stage(
            "lock",
            [
                "data-lock",
                "create",
                "--raw-dir",
                str(source / "raw"),
                "--synthetic-manifest",
                str(source / "manifest.json"),
                "--out",
                str(lock),
            ],
            work_dir,
        ),
        _run_stage(
            "ingest",
            [
                "ingest",
                "--raw-dir",
                str(source / "raw"),
                "--lock",
                str(lock),
                "--data-root",
                str(data),
            ],
            work_dir,
        ),
        _run_stage(
            "ingest_rerun_reuse",
            [
                "ingest",
                "--raw-dir",
                str(source / "raw"),
                "--lock",
                str(lock),
                "--data-root",
                str(data),
            ],
            work_dir,
        ),
        _run_stage(
            "transform", ["transform", "--data-root", str(data), "--lock", str(lock)], work_dir
        ),
    ]
    totals = read_json(source / "manifest.json")["totals"]
    con: duckdb.DuckDBPyConnection = duckdb.connect(
        str(data / "warehouse" / "prepay.duckdb"), read_only=True
    )
    try:
        panel_rows = con.sql("select count(*) from fct_hazard_panel").fetchall()[0]
        plan = con.sql(
            "explain analyze select outcome_class, count(*), avg(incentive_bps) "
            "from fct_hazard_panel where target_month between 2016 * 12 and 2017 * 12 + 11 "
            "group by 1"
        ).fetchall()
    finally:
        con.close()
    by_stage = {s["stage"]: s for s in stages}
    perf_rows = int(totals["performance_rows"])
    result = {
        "kind": "prepay-pipeline-benchmark",
        "synthetic": True,
        "measured_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "preset": preset,
        "dataset": {
            "loans": int(totals["loans"]),
            "performance_rows": perf_rows,
            "raw_bytes": _dir_bytes(source / "raw"),
            "bronze_bytes": _dir_bytes(data / "bronze"),
            "warehouse_bytes": _dir_bytes(data / "warehouse"),
            "hazard_panel_rows": int(panel_rows[0]) if panel_rows else 0,
        },
        "stages": stages,
        "throughput_rows_per_second": {
            "ingest": round(perf_rows / by_stage["ingest"]["command_seconds"]),
            "transform": round(perf_rows / by_stage["transform"]["command_seconds"]),
        },
        "query_plan_sample": plan[0][1][:4000] if plan else None,
        "host": host_description(),
        "versions": {p: metadata.version(p) for p in PACKAGES},
        "repetitions": 1,
    }
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    write_json_atomic(report_dir / f"pipeline-{preset}-{stamp}.json", result)
    return result
