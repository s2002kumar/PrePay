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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from prepay import periods
from prepay.evaluation.cohort import Predictor
from prepay.evaluation.cohort import backtest as cohort_backtest
from prepay.evaluation.runoff import runoff_backtest
from prepay.evaluation.segments import segment_report
from prepay.features.batch import PanelBatch
from prepay.features.panel import rate_path_from_bronze
from prepay.ingest.lock import DataLock
from prepay.io import read_json, sha256_file, write_json_atomic
from prepay.modeling import metrics
from prepay.modeling.registry import MANIFEST, Run, load_run
from prepay.modeling.train import CREDIT_MIN_VALIDATION_EVENTS
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
                "ADR 0006 §7 segment tables (A/E with loan-cluster intervals, poorly served cells)",
                "ADR 0006 §8 credit metrics only where credit is validated and events >= 100",
                "ADR 0006 §9 balance run-off: pool factor, principal components, truncated WAL",
                "ADR 0006 §10 informative-censoring bounds and censored-loan profiles",
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


def _score_window(
    batch: PanelBatch,
    run: Run,
    selected_name: str,
    base_val: dict[str, Any],
    credit_validated: bool,
) -> dict[str, Any]:
    """Every model's metrics, the pre-declared flags, credit gating and segments for one window."""
    predictions = {name: model.predict_proba(batch) for name, model in run.models.items()}
    predictions["selected"] = run.selected.predict_proba(batch)
    result = {name: metrics.evaluate(batch, p) for name, p in predictions.items()}
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
    result["_flags"] = {
        "beats_baselines": all(float(d["high"]) < 0 for d in differences.values()),
        "gbm_vs_baselines": gbm_vs_baselines,
        "log_loss_degradation": result["selected"]["log_loss"] > 1.2 * base_val["log_loss"],
        "prepay_calibration_degradation": result["selected"]["prepay"]["ece"]
        > 2 * base_val["prepay"]["ece"],
        "paired_difference_vs": differences,
    }
    credit_events = int((batch.outcome_class == 2).sum())
    result["_credit"] = {
        "credit_events": credit_events,
        "metrics_interpretable": credit_validated and credit_events >= CREDIT_MIN_VALIDATION_EVENTS,
    }
    result["_segments"] = segment_report(batch, predictions)
    return result


def _cohort_models(run: Run) -> dict[str, Predictor]:
    return {
        "selected": run.selected,
        **{n: run.models[n] for n in ("B1_lookup", "B2_logistic", "M1_lightgbm")},
    }


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
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    windows = {w.name: w for w in standard_windows(cutoff)}
    validation = read_json(run_dir / "validation.json")
    credit = read_json(run_dir / MANIFEST).get("credit_sufficiency")
    credit_validated = bool(credit and credit["credit_hazard_validated"])
    selected_name = sealed.payload["candidate"]
    base_val = validation[selected_name]["validation_b"]
    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    results: dict[str, Any] = {}
    try:
        for name in TEST_WINDOWS:
            batch = read_window(con, windows[name], seal=sealed)
            if batch.rows == 0:
                results[name] = {"rows": 0, "note": "no at-risk rows in this window"}
                continue
            window_result = _score_window(batch, run, selected_name, base_val, credit_validated)
            results[name] = {"window": windows[name].label, **window_result}
        history = rate_path_from_bronze(data_root / "bronze")
        cohort_models = _cohort_models(run)
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
        runoff = {
            periods.to_iso(windows[name].first - 1): runoff_backtest(
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
        "runoff_backtests": runoff,
        "credit_sufficiency": credit,
    }
    write_json_atomic(out, report)
    _read_only(out)
    return report


class _NonHoldout:
    """Stands in for a seal: the rehearsal reads only training and validation months."""

    def verify(self) -> None:
        return None


def rehearse_lockbox(run_dir: Path, data_root: Path, lock: DataLock) -> dict[str, Any]:
    """Dress rehearsal of :func:`evaluate_lockbox` on non-holdout months, before sealing.

    The lockbox writes its report only at the end, so a failure part-way (memory, a bug at full
    scale) would read the holdout and leave nothing. This runs the same window scoring on
    Validation B, and the same cohort and run-off backtests for the cohort active before
    Validation A with observation capped at the end of Validation B. It reports stage times and
    peak RSS. No test month is read, and the output is not evidence of performance: Validation B
    was already used for calibration.
    """
    from prepay.resources import peak_rss_bytes

    run = load_run(run_dir)
    if lock.fingerprint() != run.manifest["data_lock_fingerprint"]:
        raise LockboxError("data lock differs from the one the run was trained on")
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    windows = {w.name: w for w in standard_windows(cutoff)}
    selected_name = run.manifest["selection"]["selected"]
    validation = read_json(run_dir / "validation.json")
    credit = run.manifest.get("credit_sufficiency")
    credit_validated = bool(credit and credit["credit_hazard_validated"])
    window = windows["validation_b"]
    t0, cap = windows["validation_a"].first - 1, window.last
    stages: dict[str, dict[str, float]] = {}
    clock = time.perf_counter()

    def stage(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        stages[name] = {"seconds": round(now - clock, 1), "peak_rss_bytes": peak_rss_bytes()}
        clock = now

    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    try:
        batch = read_window(con, window)
        stage("read_window")
        window_result = _score_window(
            batch, run, selected_name, validation[selected_name]["validation_b"], credit_validated
        )
        stage("score_window")
        rows = batch.rows
        del batch
        history = rate_path_from_bronze(data_root / "bronze")
        cohort_models = _cohort_models(run)
        non_holdout = _NonHoldout()
        cohort = cohort_backtest(
            con, cohort_models, history, t0, seal=non_holdout, cutoff_month=cap
        )
        stage("cohort_backtest")
        runoff = runoff_backtest(
            con, cohort_models, history, t0, seal=non_holdout, cutoff_month=cap
        )
        stage("runoff_backtest")
    finally:
        con.close()
    return {
        "kind": "prepay-lockbox-rehearsal",
        "note": "non-holdout dress rehearsal; Validation B is in-sample for calibration",
        "run_id": run.manifest["run_id"],
        "synthetic": run.manifest["synthetic"],
        "window": window.label,
        "rows": rows,
        "stages": stages,
        "peak_rss_bytes": peak_rss_bytes(),
        "result": window_result,
        "cohort_backtest": {periods.to_iso(t0): cohort},
        "runoff_backtest": {periods.to_iso(t0): runoff},
    }
