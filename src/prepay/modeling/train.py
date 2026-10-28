"""Fit baselines and candidates on the training window, tune and select on validation only.

Pre-registered rules (ADR 0004):

* **Tuning**: B2's L2 strength and M1's ``num_leaves`` are chosen by Validation A log loss; M1
  early-stops on Validation A.
* **Selection**: among B1, B2 and M1, choose the *simplest* candidate whose Validation A log loss
  is not significantly worse than the best (95% loan-clustered bootstrap interval of the paired
  difference includes 0). B0 (PSA) is reference only.
* **Calibration**: temperature scaling for the selected model is adopted only if a temperature
  fitted on one loan-hash half of Validation B improves log loss on the other half, in both
  directions. The final temperature is then fitted on all of Validation B.

Test windows are never read here (:func:`prepay.modeling.windows.read_window` refuses).
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
from scipy.optimize import minimize_scalar

from prepay import periods
from prepay.arrays import FloatArray
from prepay.features.batch import PanelBatch
from prepay.ingest.lock import DataLock
from prepay.io import write_json_atomic
from prepay.modeling import metrics
from prepay.modeling.design import Preprocessor
from prepay.modeling.models import (
    GbmModel,
    HazardModel,
    LogisticModel,
    LookupBaseline,
    PsaBaseline,
    apply_temperature,
)
from prepay.modeling.registry import MANIFEST, save_models
from prepay.modeling.windows import Window, read_window, standard_windows
from prepay.provenance import (
    canonical_digest,
    feature_contract_digest,
    git_sha,
    software_lock_digest,
)
from prepay.transform import warehouse_path

log = logging.getLogger(__name__)

SIMPLICITY_ORDER = ("B1_lookup", "B2_logistic", "M1_lightgbm")
PRIMARY_METRIC = "multiclass_log_loss"
CREDIT_MIN_TRAIN_EVENTS = 1_000  # ADR 0006 §8
CREDIT_MIN_VALIDATION_EVENTS = 100


@dataclass(frozen=True, slots=True)
class TrainingConfig:
    train_sample_fraction: float | None = None
    logistic_c_grid: tuple[float, ...] = (0.01, 0.1, 1.0)
    gbm_num_leaves_grid: tuple[int, ...] = (15, 63)
    gbm_max_rounds: int = 2000
    lookup_prior_strength: float = 200.0
    bootstrap_replicates: int = 200


def fit_temperature(p: FloatArray, y: np.ndarray) -> float:
    def loss(log_t: float) -> float:
        return float(metrics.row_log_loss(apply_temperature(p, float(np.exp(log_t))), y).mean())

    result = minimize_scalar(loss, bounds=(np.log(0.25), np.log(4.0)), method="bounded")
    return float(np.exp(result.x))


def credit_sufficiency(
    con: duckdb.DuckDBPyConnection, windows: dict[str, Window]
) -> dict[str, Any]:
    """ADR 0006 §8: whether the credit hazard counts as a validated output.

    Decided on full (unsampled) training and validation counts, before any test window is read.
    """
    events = {}
    for name in ("train", "validation_a", "validation_b"):
        w = windows[name]
        events[name] = int(
            con.sql(
                "select count(*) from fct_hazard_panel "
                "where outcome_class = 2 and target_month between $first and $last",
                params={"first": w.first, "last": w.last},
            ).fetchall()[0][0]
        )
    validated = (
        events["train"] >= CREDIT_MIN_TRAIN_EVENTS
        and min(events["validation_a"], events["validation_b"]) >= CREDIT_MIN_VALIDATION_EVENTS
    )
    return {
        "rule": (
            f"validated only with >= {CREDIT_MIN_TRAIN_EVENTS} training and >= "
            f"{CREDIT_MIN_VALIDATION_EVENTS} credit dispositions in each validation window"
        ),
        "credit_events": events,
        "credit_hazard_validated": validated,
        "consequence": None
        if validated
        else "credit metrics are descriptive only; projections must treat credit exits as an "
        "assumption, not a forecast",
    }


def calibration_decision(model: HazardModel, val_b: PanelBatch) -> dict[str, Any]:
    p = model.predict_proba(val_b)
    y = val_b.outcome_class
    half = np.array([hash_fold(lid) for lid in val_b.loan_id])
    folds = []
    for fit_fold in (0, 1):
        fit_rows, eval_rows = half == fit_fold, half != fit_fold
        if not fit_rows.any() or not eval_rows.any():
            return {"adopted": False, "reason": "validation B too small to cross-fit"}
        t = fit_temperature(p[fit_rows], y[fit_rows])
        raw = float(metrics.row_log_loss(p[eval_rows], y[eval_rows]).mean())
        calibrated = float(
            metrics.row_log_loss(apply_temperature(p[eval_rows], t), y[eval_rows]).mean()
        )
        folds.append({"temperature": t, "raw_log_loss": raw, "calibrated_log_loss": calibrated})
    adopted = all(f["calibrated_log_loss"] < f["raw_log_loss"] for f in folds)
    decision: dict[str, Any] = {"adopted": adopted, "cross_fit": folds}
    if adopted:
        decision["temperature"] = fit_temperature(p, y)
    return decision


def hash_fold(loan_id: str) -> int:
    """Deterministic two-way split of loans (stable across processes, unlike hash())."""
    return int(canonical_digest(loan_id)[:8], 16) % 2


def select(val_a: PanelBatch, predictions: dict[str, FloatArray]) -> dict[str, Any]:
    losses = {
        name: float(metrics.row_log_loss(predictions[name], val_a.outcome_class).mean())
        for name in SIMPLICITY_ORDER
    }
    best = min(losses, key=losses.__getitem__)
    comparisons = {}
    for name in SIMPLICITY_ORDER:
        if name == best:
            selected = name
            break
        diff = metrics.paired_difference(val_a, predictions[name], predictions[best])
        comparisons[name] = diff
        if float(diff["low"]) <= 0.0:  # not significantly worse than the best
            selected = name
            break
    return {
        "rule": "simplest candidate not significantly worse than the best on validation_a "
        "log loss (95% loan-clustered bootstrap)",
        "validation_a_log_loss": losses,
        "best": best,
        "paired_difference_vs_best": comparisons,
        "selected": selected,
    }


def train(
    data_root: Path,
    lock: DataLock,
    out_root: Path,
    config: TrainingConfig | None = None,
    *,
    truth_dir: Path | None = None,
) -> Path:
    config = config or TrainingConfig()
    started = time.perf_counter()
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    windows = {w.name: w for w in standard_windows(cutoff)}
    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    try:
        train_batch = read_window(
            con, windows["train"], sample_fraction=config.train_sample_fraction
        )
        val_a = read_window(con, windows["validation_a"])
        val_b = read_window(con, windows["validation_b"])
        credit = credit_sufficiency(con, windows)
    finally:
        con.close()
    for name, batch in (("train", train_batch), ("validation_a", val_a), ("validation_b", val_b)):
        if batch.rows == 0:
            raise ValueError(f"window {name} has no at-risk rows")

    pre = Preprocessor.fit(train_batch)
    models: dict[str, HazardModel] = {
        "B0_psa": PsaBaseline.fit(train_batch),
        "B1_lookup": LookupBaseline.fit(train_batch, prior_strength=config.lookup_prior_strength),
    }
    tuning: dict[str, list[dict[str, float]]] = {"B2_logistic": [], "M1_lightgbm": []}
    best_logistic: tuple[float, LogisticModel] | None = None
    for c in config.logistic_c_grid:
        candidate = LogisticModel.fit(train_batch, pre, c_regularization=c)
        loss = float(
            metrics.row_log_loss(candidate.predict_proba(val_a), val_a.outcome_class).mean()
        )
        tuning["B2_logistic"].append({"c_regularization": c, "validation_a_log_loss": loss})
        if best_logistic is None or loss < best_logistic[0]:
            best_logistic = (loss, candidate)
    best_gbm: tuple[float, GbmModel] | None = None
    for leaves in config.gbm_num_leaves_grid:
        gbm = GbmModel.fit(
            train_batch, val_a, pre, num_leaves=leaves, max_rounds=config.gbm_max_rounds
        )
        loss = float(metrics.row_log_loss(gbm.predict_proba(val_a), val_a.outcome_class).mean())
        tuning["M1_lightgbm"].append(
            {
                "num_leaves": leaves,
                "best_iteration": gbm.best_iteration,
                "validation_a_log_loss": loss,
            }
        )
        if best_gbm is None or loss < best_gbm[0]:
            best_gbm = (loss, gbm)
    assert best_logistic is not None
    assert best_gbm is not None
    models["B2_logistic"] = best_logistic[1]
    models["M1_lightgbm"] = best_gbm[1]

    predictions = {
        name: {"validation_a": m.predict_proba(val_a), "validation_b": m.predict_proba(val_b)}
        for name, m in models.items()
    }
    selection = select(val_a, {n: p["validation_a"] for n, p in predictions.items()})
    calibration = calibration_decision(models[selection["selected"]], val_b)
    selection["calibration"] = calibration
    selection["temperature"] = calibration.get("temperature")

    validation = {
        name: {
            window: metrics.evaluate(batch, predictions[name][window])
            for window, batch in (("validation_a", val_a), ("validation_b", val_b))
        }
        for name in models
    }
    if truth_dir is not None:
        validation["_truth_recovery"] = truth_recovery(val_b, models, truth_dir)

    run_id = (
        dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + canonical_digest([lock.fingerprint(), asdict(config)])[:8]
    )
    run_dir = out_root / run_id
    save_models(run_dir, pre, models)
    write_json_atomic(run_dir / "validation.json", validation)
    manifest = {
        "kind": "prepay-model-run",
        "run_id": run_id,
        "synthetic": lock.synthetic,
        "dataset": lock.dataset,
        "release": lock.release,
        "data_lock_fingerprint": lock.fingerprint(),
        "feature_contract_digest": feature_contract_digest(),
        "software_lock_digest": software_lock_digest(),
        "git_sha": git_sha(),
        "windows": {name: _window_json(w) for name, w in windows.items()},
        "rows": {"train": train_batch.rows, "validation_a": val_a.rows, "validation_b": val_b.rows},
        "training_config": asdict(config),
        "tuning": tuning,
        "models": list(models),
        "primary_metric": PRIMARY_METRIC,
        "selection": selection,
        "credit_sufficiency": credit,
        "gbm_feature_importance_gain": best_gbm[1].feature_importance(),
        "feature_support": feature_support(train_batch),
        "seconds": round(time.perf_counter() - started, 1),
    }
    write_json_atomic(run_dir / MANIFEST, manifest)
    log.info(
        "model run written",
        extra={"run_id": run_id, "selected": selection["selected"], "synthetic": lock.synthetic},
    )
    return run_dir


SUPPORT_FEATURES = (
    "incentive_bps",
    "market_rate_t1",
    "rate_change_6m_bps",
    "loan_age",
    "burnout_months",
)


def feature_support(batch: PanelBatch) -> dict[str, dict[str, float]]:
    """0.5%-99.5% training range of rate-driven features, for scenario out-of-support flags."""
    support = {}
    for name in SUPPORT_FEATURES:
        values = np.asarray(batch.features[name], dtype=np.float64)
        values = values[np.isfinite(values)]
        support[name] = {
            "low": float(np.quantile(values, 0.005)),
            "high": float(np.quantile(values, 0.995)),
        }
    return support


def _window_json(w: Window) -> dict[str, Any]:
    return {"role": w.role, "first": periods.to_iso(w.first), "last": periods.to_iso(w.last)}


def truth_recovery(
    batch: PanelBatch, models: dict[str, HazardModel], truth_dir: Path
) -> dict[str, Any]:
    """Synthetic only: mean absolute error between predicted and *true* hazards on a window."""
    truth = duckdb.execute(
        "select loan_id, period, true_prepay, true_credit from read_parquet(?)",
        [f"{truth_dir.as_posix()}/*.parquet"],
    ).fetchall()
    lookup = {(lid, periods.parse_yyyymm(str(per))): (p, c) for lid, per, p, c in truth}
    true = np.array(
        [lookup[(lid, int(m))] for lid, m in zip(batch.loan_id, batch.target_month, strict=True)]
    )
    result: dict[str, Any] = {"note": "synthetic ground truth; not evidence of real accuracy"}
    for name, model in models.items():
        p = model.predict_proba(batch)
        result[name] = {
            "prepay_mae": float(np.abs(p[:, 1] - true[:, 0]).mean()),
            "credit_mae": float(np.abs(p[:, 2] - true[:, 1]).mean()),
            "true_mean_prepay": float(true[:, 0].mean()),
        }
    return result
