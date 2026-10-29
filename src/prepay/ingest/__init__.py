"""Source ingest: data lock verification, then raw files to immutable bronze Parquet."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from prepay.ingest import pmms, sflld
from prepay.ingest.lock import DataLock, LockError, verify_lock
from prepay.io import write_json_atomic

log = logging.getLogger(__name__)


def ingest_all(
    raw_dir: Path,
    lock: DataLock,
    bronze_root: Path,
    *,
    allow_malformed: bool = False,
    allow_early_end: bool = False,
) -> dict[str, Any]:
    """Verify every locked file, then ingest all archives and rate series.

    Verification happens first and covers every file, so a single changed or unexpected input
    stops the run before anything is published. A release's latest vintages report active loans
    through its cutoff, so a dataset whose last reporting period is earlier is most likely an
    older release locked under the wrong number. It is refused unless ``allow_early_end`` (a
    deliberate download of old vintages only).
    """
    problems = verify_lock(lock, raw_dir)
    if problems:
        raise LockError("data lock verification failed: " + "; ".join(problems))
    vintages = [
        sflld.ingest_archive(raw_dir, entry, lock, bronze_root, allow_malformed=allow_malformed)
        for entry in lock.sflld
    ]
    cutoff = lock.performance_cutoff_month.replace("-", "")
    observed = max(
        (
            m["period_max"]
            for v in vintages
            for m in v["members"]
            if m["file_kind"] == "performance" and m["period_max"]
        ),
        default=None,
    )
    if observed != cutoff and not allow_early_end:
        raise sflld.IngestError(
            f"latest reporting period {observed} differs from the Release {lock.release} "
            f"performance cutoff {cutoff}: the files look like a different release. Pass "
            "--allow-early-end only for a deliberate download of old vintages."
        )
    series = [pmms.ingest_series(raw_dir, entry, lock, bronze_root) for entry in lock.pmms]
    summary = {
        "kind": "prepay-ingest-summary",
        "synthetic": lock.synthetic,
        "dataset": lock.dataset,
        "release": lock.release,
        "performance_cutoff": lock.performance_cutoff,
        "lock_fingerprint": lock.fingerprint(),
        "latest_reporting_period": observed,
        "vintages": {
            str(v["vintage"]): {
                "status": v["status"],
                "rows": {m["file_kind"]: m["rows"] for m in v["members"]},
                "malformed_rows": {m["file_kind"]: m["malformed_rows"] for m in v["members"]},
                "period_range": {
                    m["file_kind"]: [m["period_min"], m["period_max"]] for m in v["members"]
                },
                "field_violations": {
                    m["file_kind"]: {k: n for k, n in m["violations"].items() if n}
                    for m in v["members"]
                },
            }
            for v in vintages
        },
        "pmms": {
            s["series"]: {
                "status": s["status"],
                "observations": s["observations"],
                "missing": s["missing_observations"],
            }
            for s in series
        },
    }
    write_json_atomic(bronze_root / "_ingest_summary.json", summary)
    return summary
