"""Run the dbt project (``transform/``) against a data root's bronze layer.

dbt runs in-process. Paths and the performance cutoff come from the arguments and the data lock,
never from the system clock. dbt's target and log directories live under the data root, so the
repository stays clean and concurrent runs on different data roots don't collide.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from collections.abc import Iterator
from pathlib import Path

from prepay.ingest.lock import DataLock

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[2] / "transform"


class TransformError(RuntimeError):
    """dbt reported a failed model or data test."""


def warehouse_path(data_root: Path) -> Path:
    return data_root / "warehouse" / "prepay.duckdb"


@contextlib.contextmanager
def _environment(values: dict[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _release_dbt_resources() -> None:
    """Close what in-process dbt keeps open after ``invoke`` returns.

    dbt-duckdb holds the DuckDB database for the life of the process (later connections then
    fail with a configuration conflict and Windows keeps the file locked), and dbt's file
    loggers keep ``dbt.log`` open. Neither has a public close API, so close them explicitly.
    """
    from dbt.adapters.duckdb.connections import DuckDBConnectionManager
    from dbt.adapters.factory import cleanup_connections
    from dbt_common.events.event_manager_client import cleanup_event_logger, get_event_manager

    cleanup_connections()
    environment = DuckDBConnectionManager._ENV
    if environment is not None:
        environment.close()
    DuckDBConnectionManager.close_all_connections()
    for dbt_logger in getattr(get_event_manager(), "loggers", []):
        python_logger = getattr(dbt_logger, "_python_logger", None)
        if isinstance(python_logger, logging.Logger):
            for handler in list(python_logger.handlers):
                handler.close()
                python_logger.removeHandler(handler)
    cleanup_event_logger()


def run_dbt(
    data_root: Path, lock: DataLock, command: str = "build", *, memory_limit: str = "80%"
) -> None:
    """Run ``dbt <command>`` (build = models + data tests) and raise on any failure.

    ``memory_limit`` is DuckDB's ``memory_limit`` (DuckDB's own default is 80% of RAM); larger
    joins and windows spill to ``<warehouse>.tmp`` instead of exhausting memory.
    """
    from dbt.cli.main import dbtRunner

    bronze = data_root / "bronze"
    if not (bronze / "_ingest_summary.json").is_file():
        raise TransformError(f"no ingested bronze layer at {bronze}; run `prepay ingest` first")
    warehouse = warehouse_path(data_root)
    warehouse.parent.mkdir(parents=True, exist_ok=True)
    dbt_dir = data_root / "dbt"
    args = [
        command,
        "--project-dir",
        str(PROJECT_DIR),
        "--profiles-dir",
        str(PROJECT_DIR),
        "--target-path",
        str(dbt_dir / "target"),
        "--log-path",
        str(dbt_dir / "logs"),
        "--vars",
        json.dumps({"performance_cutoff": lock.performance_cutoff_month}),
        "--quiet",
    ]
    environment = {
        "PREPAY_BRONZE": bronze.as_posix(),
        "PREPAY_WAREHOUSE": warehouse.as_posix(),
        "PREPAY_DUCKDB_MEMORY_LIMIT": memory_limit,
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
    }
    with _environment(environment):
        try:
            result = dbtRunner().invoke(args)
        finally:
            _release_dbt_resources()
    if not result.success:
        failures = []
        if result.result is not None:
            failures = [
                f"{r.node.name}: {r.status}"
                for r in getattr(result.result, "results", [])
                if str(r.status) not in ("success", "pass")
            ]
        raise TransformError(f"dbt {command} failed: {failures or result.exception}")
    log.info("dbt finished", extra={"command": command, "warehouse": warehouse.name})
