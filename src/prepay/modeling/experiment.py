"""Experiment runs and rolling-origin development folds (ADR 0009, ADR 0010).

An experiment run fits a declared set of families on declared windows. It writes a run
directory with the layout of a primary run (:mod:`prepay.modeling.registry`), so it can be
loaded, sealed and forward-evaluated. It **never selects**. The run names a designated model
before training (the seal needs one). Every model gets its own ADR 0004 §7 calibration
decision, and is scored with it.

Guards (ADR 0009 §2):

- no window may extend past the lock's cutoff;
- a window that reaches 2020-01 or later reads opened months. It runs only with
  ``allow_opened=True``, and the run is then labeled ``exploratory-opened-window``;
- runs on months ≤ 2019-12 are ``development`` (real data) or ``synthetic``.

Evidence produced here never confirms an improvement; only forward months can (ADR 0010).
Real-data runs are executed by the owner, and their outputs stay private (ADR 0009 §3).
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from prepay import periods
from prepay.evaluation.attribution import cohort_attribution, runoff_attribution
from prepay.evaluation.cohort import backtest as cohort_backtest
from prepay.evaluation.regimes import regime_dimensions
from prepay.evaluation.runoff import runoff_backtest
from prepay.evaluation.segments import segment_report
from prepay.features.batch import PanelBatch
from prepay.features.derived import DERIVED_VERSION, augment
from prepay.features.panel import LOAN_HASH_BUCKETS, rate_path_from_bronze
from prepay.features.panel import rate_path_from_warehouse as warehouse_rates
from prepay.ingest.lock import DataLock
from prepay.io import read_json, write_json_atomic
from prepay.modeling import metrics
from prepay.modeling.challengers import (
    VARIANTS,
    ConstrainedHazard,
    FactoredGbm,
    ice_violation_share,
)
from prepay.modeling.design import Preprocessor
from prepay.modeling.lockbox import read_only
from prepay.modeling.models import (
    GbmModel,
    HazardModel,
    LogisticModel,
    LookupBaseline,
    PsaBaseline,
)
from prepay.modeling.registry import MANIFEST, load_run, save_models
from prepay.modeling.train import PRIMARY_METRIC, calibration_decision, feature_support
from prepay.modeling.windows import Window, read_window
from prepay.provenance import (
    canonical_digest,
    feature_contract_digest,
    git_dirty,
    git_sha,
    software_lock_digest,
)
from prepay.transform import warehouse_path

log = logging.getLogger(__name__)

EXPERIMENT_KIND = "prepay-experiment-run"
OPENED_FIRST = periods.month(2020, 1)
DEVELOPMENT_LAST = periods.month(2019, 12)
FAMILIES = (
    "B0_psa",
    "B1_lookup",
    "B2_logistic",
    "M1_lightgbm",
    *VARIANTS,
    "H1_constrained_hazard",
)
DEVELOPMENT_FAMILIES = (
    "B1_lookup",
    "B2_logistic",
    "M1_lightgbm",
    *VARIANTS,
    "H1_constrained_hazard",
)
#: ADR 0009 §4 rolling origins.
V1_ORIGINS = tuple(periods.month(year, 12) for year in (2007, 2009, 2011, 2013, 2015, 2017))
REFERENCES = ("B2_logistic", "M1_lightgbm")
MONOTONE_REFERENCE_ROWS = 2000
DEVELOPMENT_REPORT = Path("evaluations") / "development.json"


class OpenedWindowError(PermissionError):
    """An experiment tried to read 2020-01 or later without the explicit exploratory flag."""


class EmptyWindowError(ValueError):
    """A window of the experiment has no at-risk rows (e.g. a fold before the data starts)."""


@dataclass(frozen=True, slots=True)
class ExperimentWindows:
    """Target-month windows (month indices, inclusive); ``evaluate`` only for development folds."""

    train_last: int
    tune: tuple[int, int]
    calibrate: tuple[int, int]
    evaluate: tuple[int, int] | None = None

    @classmethod
    def rolling_origin(cls, origin: int) -> ExperimentWindows:
        """ADR 0009 §4: train ≤ o-24, tune o-23..o-12, calibrate o-11..o, evaluate o+1..o+24."""
        last = min(origin + 24, DEVELOPMENT_LAST)
        if last <= origin:
            raise ValueError("a development fold needs evaluation months up to 2019-12")
        return cls(
            origin - 24, (origin - 23, origin - 12), (origin - 11, origin), (origin + 1, last)
        )

    @classmethod
    def ending_at(cls, last_month: int) -> ExperimentWindows:
        """Train ≤ last-24, tune the next 12 months, calibrate the last 12 (no evaluation)."""
        return cls(
            last_month - 24, (last_month - 23, last_month - 12), (last_month - 11, last_month)
        )

    @property
    def last_month(self) -> int:
        return max(self.calibrate[1], self.evaluate[1] if self.evaluate else 0)

    def windows(self) -> dict[str, Window]:
        out = {
            "train": Window("train", "train", 0, self.train_last),
            "tune": Window("tune", "validation", *self.tune),
            "calibrate": Window("calibrate", "validation", *self.calibrate),
        }
        if self.evaluate is not None:
            out["evaluate"] = Window("evaluate", "validation", *self.evaluate)
        return out


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    experiment_id: str
    windows: ExperimentWindows
    models: tuple[str, ...]
    designated: str
    train_sample_fraction: float | None = None
    sample_index: int = 0
    seed: int | None = None
    logistic_c_grid: tuple[float, ...] = (0.01, 0.1, 1.0)
    gbm_num_leaves_grid: tuple[int, ...] = (15, 63)
    gbm_max_rounds: int = 2000
    hazard_l2_grid: tuple[float, ...] = (1e-4, 1e-3, 1e-2)
    lookup_prior_strength: float = 200.0

    def __post_init__(self) -> None:
        unknown = set(self.models) - set(FAMILIES)
        if unknown:
            raise ValueError(f"unknown families {sorted(unknown)}; known: {list(FAMILIES)}")
        if self.designated not in self.models:
            raise ValueError("the designated model must be one of the experiment's models")
        if not self.experiment_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("experiment_id may contain only letters, digits, '-' and '_'")


def preset(name: str, cutoff_month: int) -> ExperimentConfig:
    """The ADR 0010 member runs: ``DEV2017`` (ADR 0008 windows) and ``REFIT2026`` (to cutoff)."""
    m = periods.month
    if name == "DEV2017":
        windows = ExperimentWindows(
            m(2017, 12), (m(2018, 1), m(2018, 12)), (m(2019, 1), m(2019, 12))
        )
        models = (*VARIANTS, "H1_constrained_hazard")
        return ExperimentConfig("DEV2017", windows, models, designated="X2_factored_gbm")
    if name == "REFIT2026":
        models = ("M1_lightgbm", "B2_logistic", "X2_factored_gbm", "H1_constrained_hazard")
        return ExperimentConfig(
            "REFIT2026",
            ExperimentWindows.ending_at(cutoff_month),
            models,
            designated="X2_factored_gbm",
        )
    raise KeyError(f"unknown preset {name!r}; known: DEV2017, REFIT2026")


def evidence_class(lock: DataLock, last_month: int, *, allow_opened: bool) -> str:
    """ADR 0009 §2 label for reading months through ``last_month``; refuses opened months
    without the explicit flag."""
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    if last_month > cutoff:
        raise ValueError("experiment windows extend past the data lock's cutoff")
    opened = last_month >= OPENED_FIRST
    if opened and not allow_opened:
        raise OpenedWindowError(
            "this experiment reads months from 2020-01 on, which the primary lockbox has opened. "
            "Pass the explicit exploratory flag; the run is then labeled "
            "exploratory-opened-window and is not evidence of improvement on those months"
        )
    if lock.synthetic:
        return "synthetic"
    return "exploratory-opened-window" if opened else "development"


class DevelopmentAccess:
    """Stands in for a seal in development folds: the guard above has already checked months."""

    def verify(self) -> None:
        return None


# --------------------------------------------------------------------------- fitting
def _tune_loss(model: HazardModel, tune: PanelBatch) -> float:
    return float(metrics.row_log_loss(model.predict_proba(tune), tune.outcome_class).mean())


def fit_family(
    name: str,
    config: ExperimentConfig,
    train: PanelBatch,
    tune: PanelBatch,
    pre: Preprocessor,
) -> tuple[HazardModel, list[dict[str, Any]]]:
    """Fit one family; grid settings are chosen on the tune window's log loss (ADR 0004 §5)."""
    if name == "B0_psa":
        return PsaBaseline.fit(train), []
    if name == "B1_lookup":
        return LookupBaseline.fit(train, prior_strength=config.lookup_prior_strength), []
    grid: list[dict[str, Any]]
    if name == "B2_logistic":
        grid = [{"c_regularization": c} for c in config.logistic_c_grid]
    elif name in ("M1_lightgbm", *VARIANTS):
        grid = [{"num_leaves": leaves} for leaves in config.gbm_num_leaves_grid]
    elif name == "H1_constrained_hazard":
        grid = [{"l2": l2} for l2 in config.hazard_l2_grid]
    else:
        raise ValueError(f"unknown family {name!r}")
    best: tuple[float, HazardModel] | None = None
    log_rows = []
    for settings in grid:
        model: HazardModel
        if name == "B2_logistic":
            model = LogisticModel.fit(train, pre, **settings)
        elif name == "M1_lightgbm":
            model = GbmModel.fit(
                train, tune, pre, max_rounds=config.gbm_max_rounds, seed=config.seed, **settings
            )
        elif name in VARIANTS:
            model = FactoredGbm.fit(
                train,
                tune,
                pre,
                variant=name,
                max_rounds=config.gbm_max_rounds,
                seed=config.seed,
                **settings,
            )
        else:
            model = ConstrainedHazard.fit(train, pre, **settings)
        loss = _tune_loss(model, tune)
        row = {**settings, "tune_log_loss": loss}
        if isinstance(model, GbmModel):
            row["best_iteration"] = model.best_iteration
        if isinstance(model, FactoredGbm):
            row["iterations"] = model.iterations
        log_rows.append(row)
        if best is None or loss < best[0]:
            best = (loss, model)
    assert best is not None
    return best[1], log_rows


def setter(feature: str) -> Callable[[PanelBatch, float], PanelBatch]:
    """``set(batch, v)``: the batch with ``feature`` set to ``v`` on every row."""

    def set_value(batch: PanelBatch, value: float) -> PanelBatch:
        return replace(batch, features={**batch.features, feature: np.full(batch.rows, value)})

    return set_value


def monotonicity(models: dict[str, HazardModel], reference: PanelBatch) -> dict[str, Any]:
    """Column-wise ICE checks on the payoff probability (and hazard, for factored families).

    Incentive is set alone, holding every other input as observed. For the factored families
    that is exactly what their monotone constraints guarantee for the payoff hazard ``h``. The
    payoff probability ``(1 - c) h`` can still move with the credit hazard, so it is reported
    too.
    """
    incentive = tuple(float(v) for v in range(-400, 301, 50))
    burnout = tuple(float(v) for v in range(0, 121, 12))
    out: dict[str, Any] = {"reference_rows": reference.rows}
    for name, model in models.items():
        row = {
            "payoff_probability_falls_with_incentive": ice_violation_share(
                model, reference, setter("incentive_bps"), incentive, direction=1
            ),
            "payoff_probability_rises_with_burnout": ice_violation_share(
                model, reference, setter("burnout_months"), burnout, direction=-1
            ),
        }
        if isinstance(model, FactoredGbm | ConstrainedHazard):
            hazard_only = _PayoffHazard(model)
            row["payoff_hazard_falls_with_incentive"] = ice_violation_share(
                hazard_only, reference, setter("incentive_bps"), incentive, direction=1
            )
            row["payoff_hazard_rises_with_burnout"] = ice_violation_share(
                hazard_only, reference, setter("burnout_months"), burnout, direction=-1
            )
        out[name] = row
    return out


@dataclass(frozen=True)
class _PayoffHazard:
    model: FactoredGbm | ConstrainedHazard

    def predict_proba(self, batch: PanelBatch) -> np.ndarray:
        _, h = self.model.hazards(batch)
        return np.column_stack([1.0 - h, h, np.zeros_like(h)])


# --------------------------------------------------------------------------- runs
def _window_json(w: Window) -> dict[str, Any]:
    return {"role": w.role, "first": periods.to_iso(w.first), "last": periods.to_iso(w.last)}


def run_experiment(
    data_root: Path,
    lock: DataLock,
    out_root: Path,
    config: ExperimentConfig,
    *,
    allow_opened: bool = False,
) -> Path:
    """Fit, calibrate and record one experiment run; development folds are also evaluated."""
    import lightgbm

    started = time.perf_counter()
    evidence = evidence_class(lock, config.windows.last_month, allow_opened=allow_opened)
    windows = config.windows.windows()
    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    try:
        rates = warehouse_rates(con)
        train = read_window(
            con,
            windows["train"],
            sample_fraction=config.train_sample_fraction,
            sample_index=config.sample_index,
        )
        tune = read_window(con, windows["tune"])
        calibrate = read_window(con, windows["calibrate"])
    finally:
        con.close()
    for name, batch in (("train", train), ("tune", tune), ("calibrate", calibrate)):
        if batch.rows == 0:
            raise EmptyWindowError(f"window {name} of {config.experiment_id} has no rows")
    train, tune, calibrate = (augment(b, rates) for b in (train, tune, calibrate))

    pre = Preprocessor.fit(train)
    support = feature_support(train)
    models: dict[str, HazardModel] = {}
    tuning: dict[str, list[dict[str, Any]]] = {}
    for name in config.models:
        models[name], tuning[name] = fit_family(name, config, train, tune, pre)
        log.info("experiment family fitted", extra={"family": name, "run": config.experiment_id})
    rows = {"train": train.rows, "tune": tune.rows, "calibrate": calibrate.rows}
    del train

    calibration = {name: calibration_decision(m, calibrate) for name, m in models.items()}
    validation = {
        name: {
            "tune": metrics.evaluate(tune, model.predict_proba(tune)),
            "calibrate": metrics.evaluate(calibrate, model.predict_proba(calibrate)),
        }
        for name, model in models.items()
    }
    reference = calibrate.slice(0, min(calibrate.rows, MONOTONE_REFERENCE_ROWS))
    checks = monotonicity(models, reference)

    config_json = asdict(config)
    config_digest = canonical_digest(config_json)
    run_id = (
        dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        + f"-{config.experiment_id}-"
        + canonical_digest([lock.fingerprint(), config_digest])[:8]
    )
    run_dir = out_root / run_id
    if run_dir.exists():
        raise FileExistsError(f"{run_dir} exists; experiment runs are written once")
    save_models(run_dir, pre, models)
    write_json_atomic(run_dir / "validation.json", validation)
    designated = calibration[config.designated]
    kept = (
        None
        if config.train_sample_fraction is None
        else round(config.train_sample_fraction * LOAN_HASH_BUCKETS)
    )
    manifest = {
        "kind": EXPERIMENT_KIND,
        "run_id": run_id,
        "experiment_id": config.experiment_id,
        "evidence_class": evidence,
        "synthetic": lock.synthetic,
        "dataset": lock.dataset,
        "release": lock.release,
        "data_lock_fingerprint": lock.fingerprint(),
        "feature_contract_digest": feature_contract_digest(),
        "derived_feature_version": DERIVED_VERSION,
        "software_lock_digest": software_lock_digest(),
        "git_sha": git_sha(),
        "git_dirty": git_dirty(),
        "duckdb_version": duckdb.__version__,
        "lightgbm_version": lightgbm.__version__,
        "windows": {name: _window_json(w) for name, w in windows.items()},
        "rows": rows,
        "config": config_json,
        "config_digest": config_digest,
        "training_sample": {
            "fraction": config.train_sample_fraction,
            "index": config.sample_index,
            "definition": "duckdb hash(loan_id) % 10000 in [index * kept, (index + 1) * kept)",
            "kept_buckets": kept,
        },
        "models": list(models),
        "primary_metric": PRIMARY_METRIC,
        "selection": {
            "selected": config.designated,
            "rule": "designated before training; experiment runs never select (ADR 0010)",
            "temperature": designated.get("temperature"),
            "calibration": designated,
        },
        "calibration": calibration,
        "tuning": tuning,
        "monotonicity": checks,
        "feature_support": support,
        "seconds": round(time.perf_counter() - started, 1),
    }
    write_json_atomic(run_dir / MANIFEST, manifest)
    if config.windows.evaluate is not None:
        report = evaluate_development(run_dir, data_root, lock, allow_opened=allow_opened)
        target = run_dir / DEVELOPMENT_REPORT
        write_json_atomic(target, report)
        read_only(target)
    log.info("experiment run written", extra={"run_id": run_id, "evidence_class": evidence})
    return run_dir


def _overall_ae(result: dict[str, Any]) -> float | None:
    expected = result["prepay"]["mean_predicted"] * result["rows"]
    return result["events"]["prepay"] / expected if expected > 0 else None


def evaluate_development(
    run_dir: Path, data_root: Path, lock: DataLock, *, allow_opened: bool = False
) -> dict[str, Any]:
    """Score a fold's models, each with its own calibration, on its evaluation window.

    Metrics, paired differences vs B2 and M1, calibration by public-rate regime (D4), and the
    cohort and run-off backtests at ``t0`` = the fold origin with error attribution (D5).
    """
    run = load_run(run_dir)
    manifest = run.manifest
    window_json = manifest["windows"].get("evaluate")
    if window_json is None:
        raise ValueError(f"{run_dir.name} has no evaluation window")
    first, last = periods.parse_iso(window_json["first"]), periods.parse_iso(window_json["last"])
    evidence = evidence_class(lock, last, allow_opened=allow_opened)
    window = Window("evaluate", "validation", first, last)
    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    try:
        rates = warehouse_rates(con)
        batch = augment(read_window(con, window), rates)
        calibrated = {name: run.calibrated(name) for name in run.models}
        predictions = {name: model.predict_proba(batch) for name, model in calibrated.items()}
        history = rate_path_from_bronze(data_root / "bronze")
        access = DevelopmentAccess()
        cohort = cohort_backtest(
            con, calibrated, history, first - 1, seal=access, cutoff_month=last
        )
        runoff = runoff_backtest(
            con, calibrated, history, first - 1, seal=access, cutoff_month=last
        )
    finally:
        con.close()
    results = {name: metrics.evaluate(batch, p) for name, p in predictions.items()}
    paired = {
        name: {
            ref: metrics.paired_difference(batch, predictions[name], predictions[ref])
            for ref in REFERENCES
            if ref in predictions and ref != name
        }
        for name in predictions
    }
    dimensions = regime_dimensions(rates)
    regimes = {
        name: segment_report(batch, {name: p}, selected=name, dimensions=dimensions)
        for name, p in predictions.items()
    }
    return {
        "kind": "prepay-development-evaluation",
        "evidence_class": evidence,
        "run_id": manifest["run_id"],
        "synthetic": manifest["synthetic"],
        "window": window.label,
        "note": "development evidence: designed after the 2020-26 outcomes were seen; ranks and "
        "explains candidates, never confirms them (ADR 0009 §2)",
        "metrics": results,
        "overall_payoff_ae": {name: _overall_ae(r) for name, r in results.items()},
        "paired_log_loss_difference": paired,
        "regime_calibration": regimes,
        "cohort_backtest": cohort,
        "cohort_attribution": cohort_attribution(cohort),
        "runoff_backtest": runoff,
        "runoff_attribution": runoff_attribution(runoff),
    }


# --------------------------------------------------------------------------- rolling origin
def summarize_fold(report: dict[str, Any]) -> dict[str, Any]:
    """The per-model numbers a reviewer compares across folds."""
    attribution = report["cohort_attribution"].get("horizons", {})
    last_horizon = list(attribution)[-1] if attribution else None
    models: dict[str, Any] = {}
    for name, result in report["metrics"].items():
        regime = report["regime_calibration"][name]
        cells = [
            cell
            for dimension in regime["dimensions"].values()
            for cell in dimension.values()
            if "suppressed" not in cell and not cell["low_event"]
        ]
        models[name] = {
            "log_loss": result["log_loss"],
            "brier": result["brier"],
            "cpr_proxy_bias_pp": result["cpr_proxy"]["bias_pp"],
            "cpr_proxy_mae_pp": result["cpr_proxy"]["mae_pp"],
            "overall_payoff_ae": report["overall_payoff_ae"][name],
            "paired_vs": report["paired_log_loss_difference"][name],
            "regime_cells_evaluable": len(cells),
            "regime_cells_poorly_served": sum(bool(c["poorly_served"]) for c in cells),
            "cohort_errors_pp": (
                attribution[last_horizon]["models"].get(name) if last_horizon else None
            ),
        }
    return {"window": report["window"], "cohort_horizon": last_horizon, "models": models}


def aggregate_folds(folds: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Fold wins, ranks, worst-fold gap and paired-difference tallies (no pooled tests)."""
    scored = {k: v for k, v in folds.items() if "models" in v}
    names = sorted({name for fold in scored.values() for name in fold["models"]})
    table: dict[str, Any] = {
        name: {"folds": 0, "wins": 0, "ranks": [], "gaps_to_fold_best": []} for name in names
    }
    for fold in scored.values():
        losses = {n: m["log_loss"] for n, m in fold["models"].items()}
        best = min(losses.values())
        order = sorted(losses, key=losses.__getitem__)
        for name, loss in losses.items():
            entry = table[name]
            entry["folds"] += 1
            entry["wins"] += int(order[0] == name)
            entry["ranks"].append(order.index(name) + 1)
            entry["gaps_to_fold_best"].append(loss - best)
        for name, model in fold["models"].items():
            for ref, diff in model["paired_vs"].items():
                tally = table[name].setdefault(
                    f"vs_{ref}", {"better": 0, "worse": 0, "not_distinguishable": 0}
                )
                if float(diff["high"]) < 0:
                    tally["better"] += 1
                elif float(diff["low"]) > 0:
                    tally["worse"] += 1
                else:
                    tally["not_distinguishable"] += 1
    for entry in table.values():
        entry["mean_rank"] = float(np.mean(entry["ranks"])) if entry["ranks"] else None
        entry["worst_gap_to_fold_best"] = (
            max(entry["gaps_to_fold_best"]) if entry["gaps_to_fold_best"] else None
        )
    return table


def rolling_origin(
    data_root: Path,
    lock: DataLock,
    out_root: Path,
    base: ExperimentConfig,
    origins: Sequence[int] = V1_ORIGINS,
) -> Path:
    """Run every ADR 0009 §4 fold and write one summary report (development evidence only)."""
    folds: dict[str, dict[str, Any]] = {}
    runs: dict[str, str] = {}
    for origin in origins:
        label = periods.to_iso(origin)
        config = replace(
            base,
            experiment_id=f"V1-{label}",
            windows=ExperimentWindows.rolling_origin(origin),
        )
        try:
            run_dir = run_experiment(data_root, lock, out_root, config)
        except EmptyWindowError as exc:
            folds[label] = {"skipped": str(exc)}
            continue
        runs[label] = run_dir.name
        folds[label] = summarize_fold(read_json(run_dir / DEVELOPMENT_REPORT))
    summary = {
        "kind": "prepay-rolling-origin",
        "evidence_class": "synthetic" if lock.synthetic else "development",
        "note": "fold results are serially dependent; no significance test is pooled across "
        "folds (ADR 0009 §4). Development evidence never confirms a candidate.",
        "data_lock_fingerprint": lock.fingerprint(),
        "base_config_digest": canonical_digest(asdict(base)),
        "origins": [periods.to_iso(o) for o in origins],
        "runs": runs,
        "folds": folds,
        "aggregate": aggregate_folds(folds),
    }
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = out_root / f"rolling-origin-{stamp}.json"
    write_json_atomic(target, summary)
    read_only(target)
    return target
