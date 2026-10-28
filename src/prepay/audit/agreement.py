"""Label and feature audits at full-sample scale: independent implementations must agree.

The audit reads the warehouse and the bronze layer for disjoint loan-hash slices and reports
**only agreement counts** (ADR 0006 §6). No loan identifiers, rows or outcome rates are emitted.
"""

from __future__ import annotations

import collections
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from prepay import periods
from prepay.audit import label_oracle
from prepay.features import CATEGORICAL, NUMERIC, compute_features
from prepay.features.panel import LOAN_HASH_BUCKETS, load_statics, rate_path_from_bronze, read_panel
from prepay.ingest.lock import DataLock
from prepay.transform import warehouse_path


def _compare(sql: dict[Any, Any], oracle: dict[Any, Any]) -> dict[str, Any]:
    shared = sql.keys() & oracle.keys()
    differing = collections.Counter(
        f"{_kind(oracle[k])} -> {_kind(sql[k])}" for k in shared if sql[k] != oracle[k]
    )
    return {
        "oracle": len(oracle),
        "sql": len(sql),
        "agree": sum(1 for k in shared if sql[k] == oracle[k]),
        "only_in_sql": len(sql.keys() - oracle.keys()),
        "only_in_oracle": len(oracle.keys() - sql.keys()),
        "value_mismatch_by_kind": dict(differing),
    }


def _kind(value: Any) -> str:
    return str(value[0]) if isinstance(value, tuple) else str(value)


def label_agreement(data_root: Path, lock: DataLock, buckets: tuple[int, int]) -> dict[str, Any]:
    """Quarantine, exclusion, first-event and panel-outcome agreement for one loan slice."""
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    oracle = label_oracle.run(data_root / "bronze", cutoff, buckets)
    where = label_oracle.bucket_clause(buckets)
    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:

        def rows(sql: str) -> list[tuple[Any, ...]]:
            return con.sql(f"{sql} and {where}").fetchall()

        quarantined = {
            r[0] for r in rows("select loan_id from int_loan_quality where is_quarantined")
        }
        excluded = {
            r[0]
            for r in rows(
                "select loan_id from int_loan_quality where is_excluded and not is_quarantined"
            )
        }
        events = {
            r[0]: (r[1], r[2])
            for r in rows("select loan_id, event_type, event_month from int_exit_events where true")
        }
        panel = {
            (r[0], r[1]): r[2]
            for r in rows("select loan_id, target_month, outcome from fct_hazard_panel where true")
        }
    return {
        "buckets": list(buckets),
        "quarantined": _compare(
            dict.fromkeys(quarantined, True), dict.fromkeys(oracle.quarantined, True)
        ),
        "excluded": _compare(dict.fromkeys(excluded, True), dict.fromkeys(oracle.excluded, True)),
        "first_events": _compare(events, oracle.events),
        "panel_outcomes": _compare(panel, oracle.panel),
    }


def feature_parity(data_root: Path, sample_fraction: float) -> dict[str, Any]:
    """Gold-panel features vs the Python state machine on a loan-hash sample."""
    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
        batch = read_panel(con, 0, periods.month(2100, 1), sample_fraction=sample_fraction)
        loan_ids, statics = load_statics(con)
    position = {lid: i for i, lid in enumerate(loan_ids)}
    loan_index = np.array([position[lid] for lid in batch.loan_id], dtype=np.int64)
    python = compute_features(
        statics, rate_path_from_bronze(data_root / "bronze"), loan_index, batch.target_month
    )
    report: dict[str, Any] = {"rows": batch.rows, "loans": len(position), "features": {}}
    for name in NUMERIC:
        a = np.asarray(python[name], dtype=np.float64)
        b = np.asarray(batch.features[name], dtype=np.float64)
        both_nan = np.isnan(a) & np.isnan(b)
        close = np.isclose(a, b, rtol=1e-12, atol=1e-9) | both_nan
        diff = np.abs(a - b)[~both_nan]
        report["features"][name] = {
            "mismatches": int((~close).sum()),
            "max_abs_difference": float(np.nanmax(diff)) if diff.size else 0.0,
        }
    for name in CATEGORICAL:
        mismatches = sum(
            1 for x, y in zip(python[name], batch.features[name], strict=True) if x != y
        )
        report["features"][name] = {"mismatches": mismatches}
    report["all_match"] = all(f["mismatches"] == 0 for f in report["features"].values())
    return report


def run_audit(
    data_root: Path, lock: DataLock, *, slices: int = 5, slice_buckets: int = 100
) -> dict[str, Any]:
    """Labels on ``slices`` disjoint slices of ``slice_buckets / 10,000`` of loans each;
    features on the first slice."""
    if slices * slice_buckets > LOAN_HASH_BUCKETS:
        raise ValueError("slices exceed the hash range")
    labels = [
        label_agreement(data_root, lock, (i * slice_buckets, (i + 1) * slice_buckets))
        for i in range(slices)
    ]
    totals: dict[str, dict[str, int]] = {}
    for part in ("quarantined", "excluded", "first_events", "panel_outcomes"):
        totals[part] = {
            key: sum(int(s[part][key]) for s in labels)
            for key in ("oracle", "sql", "agree", "only_in_sql", "only_in_oracle")
        }
        totals[part]["value_mismatch"] = sum(
            sum(s[part]["value_mismatch_by_kind"].values()) for s in labels
        )
    return {
        "kind": "prepay-audit",
        "synthetic": lock.synthetic,
        "loan_share_audited": slices * slice_buckets / LOAN_HASH_BUCKETS,
        "labels": {"slices": labels, "totals": totals},
        "features": feature_parity(data_root, slice_buckets / LOAN_HASH_BUCKETS),
        "labels_all_agree": all(
            t["only_in_sql"] == t["only_in_oracle"] == t["value_mismatch"] == 0
            for t in totals.values()
        ),
    }
