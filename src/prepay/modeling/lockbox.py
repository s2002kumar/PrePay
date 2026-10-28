"""Sealing a candidate and the one-shot holdout evaluation (MODELING §5, ARCHITECTURE §7).

``seal`` freezes a run: a digest over every artifact, the evaluation plan and the pre-declared
report flags, written once. ``evaluate_lockbox`` verifies the seal, refuses if a first result
already exists, scores every model on every test window, and writes the result once, read-only.
Later experiments need a new run; they never replace the first report.
"""

from __future__ import annotations

import datetime as dt
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from prepay import periods
from prepay.evaluation.cohort import backtest as cohort_backtest
from prepay.features.panel import rate_path_from_bronze
from prepay.ingest.lock import DataLock
from prepay.io import read_json, sha256_file, write_json_atomic
from prepay.modeling import metrics
from prepay.modeling.registry import MANIFEST, load_run
from prepay.modeling.windows import read_window, standard_windows
from prepay.provenance import tree_digest
from prepay.transform import warehouse_path

SEAL = "seal.json"
FIRST_EVALUATION = Path("evaluations") / "first.json"
TEST_WINDOWS = ("test_a", "test_b", "test_c")
REPORT_FLAGS = {
    "beats_baselines": "selected model's paired log-loss difference vs each other baseline "
    "(B1, B2) has a 95% loan-clustered bootstrap interval entirely below 0",
    "gbm_vs_baselines": "M1's paired log-loss difference vs B1 and vs B2, reported on every "
    "window whichever model was selected",
    "log_loss_degradation": "selected model's test log loss exceeds its validation_b log loss "
    "by more than 20%",
    "prepay_calibration_degradation": "prepay ECE on test exceeds twice its validation_b ECE",
}


class SealError(RuntimeError):
    """The run is unsealed, already sealed, or its artifacts no longer match the seal."""


class LockboxError(RuntimeError):
    """The holdout was already evaluated for this seal, or inputs do not match."""


def candidate_digest(run_dir: Path) -> str:
    return tree_digest(run_dir, exclude=(SEAL, "evaluations"))


@dataclass(frozen=True)
class Seal:
    run_dir: Path
    payload: dict[str, Any]

    def verify(self) -> None:
        if candidate_digest(self.run_dir) != self.payload["candidate_digest"]:
            raise SealError(f"artifacts of {self.run_dir.name} changed after sealing")


def _read_only(path: Path) -> None:
    os.chmod(path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def seal(run_dir: Path) -> Seal:
    target = run_dir / SEAL
    if target.exists():
        raise SealError(f"{run_dir.name} is already sealed; seals are write-once")
    manifest = read_json(run_dir / MANIFEST)
    payload = {
        "kind": "prepay-seal",
        "run_id": manifest["run_id"],
        "synthetic": manifest["synthetic"],
        "sealed_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "candidate": manifest["selection"]["selected"],
        "temperature": manifest["selection"].get("temperature"),
        "candidate_digest": candidate_digest(run_dir),
        "data_lock_fingerprint": manifest["data_lock_fingerprint"],
        "primary_metric": manifest["primary_metric"],
        "evaluation_plan": {
            "windows": list(TEST_WINDOWS),
            "models": manifest["models"],
            "metrics": [
                "log_loss",
                "brier",
                "ece",
                "auroc",
                "average_precision",
                "full_payoff_only_CPR_proxy bias/mae",
                "loan-clustered intervals",
                "cohort run-off at 6/12/24m vs Aalen-Johansen (hindsight and as-of rates)",
            ],
        },
        "report_flags": REPORT_FLAGS,
        "allowed_exclusions": "quarantine and exclusion rules of ADR 0003, as implemented",
    }
    write_json_atomic(target, payload)
    _read_only(target)
    return Seal(run_dir, payload)


def load_seal(run_dir: Path) -> Seal:
    target = run_dir / SEAL
    if not target.is_file():
        raise SealError(f"{run_dir.name} is not sealed; run `prepay seal` first")
    found = Seal(run_dir, read_json(target))
    found.verify()
    return found


def evaluate_lockbox(run_dir: Path, data_root: Path, lock: DataLock) -> dict[str, Any]:
    sealed = load_seal(run_dir)
    out = run_dir / FIRST_EVALUATION
    if out.exists():
        raise LockboxError(
            f"{run_dir.name} was already evaluated ({out}); the first report is immutable. "
            "Train a new run for further experiments."
        )
    if lock.fingerprint() != sealed.payload["data_lock_fingerprint"]:
        raise LockboxError("data lock differs from the one the run was trained on")
    run = load_run(run_dir)
    selected = run.selected
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    windows = {w.name: w for w in standard_windows(cutoff)}
    validation = read_json(run_dir / "validation.json")
    selected_name = sealed.payload["candidate"]
    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    results: dict[str, Any] = {}
    try:
        for name in TEST_WINDOWS:
            batch = read_window(con, windows[name], seal=sealed)
            if batch.rows == 0:
                results[name] = {"rows": 0, "note": "no at-risk rows in this window"}
                continue
            predictions = {
                model_name: model.predict_proba(batch) for model_name, model in run.models.items()
            }
            predictions["selected"] = selected.predict_proba(batch)
            window_result = {
                model_name: metrics.evaluate(batch, p) for model_name, p in predictions.items()
            }
            # The selected model against the *other* baselines, and the GBM against B1 and B2
            # on every holdout whichever model was selected (MODELING §9).
            differences = {
                ref: metrics.paired_difference(batch, predictions["selected"], predictions[ref])
                for ref in ("B1_lookup", "B2_logistic")
                if ref != selected_name
            }
            gbm_vs_baselines = {
                ref: metrics.paired_difference(batch, predictions["M1_lightgbm"], predictions[ref])
                for ref in ("B1_lookup", "B2_logistic")
            }
            base_val = validation[selected_name]["validation_b"]
            window_result["_flags"] = {
                "beats_baselines": all(float(d["high"]) < 0 for d in differences.values()),
                "gbm_vs_baselines": gbm_vs_baselines,
                "log_loss_degradation": window_result["selected"]["log_loss"]
                > 1.2 * base_val["log_loss"],
                "prepay_calibration_degradation": window_result["selected"]["prepay"]["ece"]
                > 2 * base_val["prepay"]["ece"],
                "paired_difference_vs": differences,
            }
            results[name] = {"window": windows[name].label, **window_result}
        history = rate_path_from_bronze(data_root / "bronze")
        cohort_models = {
            "selected": selected,
            **{n: run.models[n] for n in ("B1_lookup", "B2_logistic", "M1_lightgbm")},
        }
        cohorts = {
            periods.to_iso(windows[name].first - 1): cohort_backtest(
                con,
                cohort_models,
                history,
                windows[name].first - 1,
                seal=sealed,
                cutoff_month=cutoff,
            )
            for name in TEST_WINDOWS
        }
    finally:
        con.close()
    report = {
        "kind": "prepay-lockbox-first-evaluation",
        "run_id": sealed.payload["run_id"],
        "synthetic": sealed.payload["synthetic"],
        "candidate": selected_name,
        "candidate_digest": sealed.payload["candidate_digest"],
        "seal_sha256": sha256_file(run_dir / SEAL),
        "evaluated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "results": results,
        "cohort_backtests": cohorts,
    }
    write_json_atomic(out, report)
    _read_only(out)
    return report
