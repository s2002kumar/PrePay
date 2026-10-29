"""Incentive-response diagnostics for the B1-vs-B2 investigation (ADR 0006 §11).

``incentive_response`` is a partial-dependence curve: every reference row is re-scored with its
incentive set to each grid value, everything else held as observed, and the predicted monthly
payoff hazards are averaged. On synthetic data ``true_incentive_response`` gives the same curve
for the generator's true hazard, so a model's shape error is visible directly. ``bin_support``
counts training rows per B1 incentive bin to show where the lookup has to shrink.

These read training or validation rows only, never a sealed test window.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from prepay.arrays import FloatArray
from prepay.features.batch import PanelBatch
from prepay.finance.rates import cpr_from_smm
from prepay.ingest.lock import DataLock
from prepay.modeling.models import INCENTIVE_EDGES, HazardModel

if TYPE_CHECKING:
    from prepay.modeling.experiment import ExperimentConfig

DEFAULT_GRID = tuple(float(x) for x in range(-400, 325, 25))


def _with_incentive(batch: PanelBatch, value: float) -> PanelBatch:
    features = dict(batch.features)
    features["incentive_bps"] = np.full(batch.rows, value)
    return replace(batch, features=features)


def incentive_response(
    models: Mapping[str, HazardModel], reference: PanelBatch, grid: Sequence[float] = DEFAULT_GRID
) -> dict[str, Any]:
    """Mean predicted monthly payoff hazard (and its CPR) per incentive grid value."""
    curves: dict[str, list[dict[str, float]]] = {name: [] for name in models}
    for value in grid:
        shifted = _with_incentive(reference, value)
        for name, model in models.items():
            smm = float(model.predict_proba(shifted)[:, 1].mean())
            curves[name].append(
                {"incentive_bps": value, "smm": smm, "cpr": float(cpr_from_smm(smm))}
            )
    return {"reference_rows": reference.rows, "grid": list(grid), "curves": curves}


def true_incentive_response(
    reference: PanelBatch, grid: Sequence[float] = DEFAULT_GRID
) -> list[dict[str, float]]:
    """Synthetic only: the generator's true payoff hazard over the same rows and grid."""
    from prepay.synthetic.truth import LoanState, outcome_probabilities

    f = reference.features
    out = []
    for value in grid:
        total = 0.0
        for month in np.unique(reference.target_month):
            rows = reference.target_month == month
            state = LoanState(
                incentive_bps=np.full(int(rows.sum()), value),
                age_months=np.asarray(f["loan_age"], dtype=np.float64)[rows].astype(np.int64),
                burnout_months=np.asarray(f["burnout_months"], dtype=np.float64)[rows].astype(
                    np.int64
                ),
                calendar_month=int(month),
                fico=np.asarray(f["credit_score"], dtype=np.float64)[rows],
                ltv=np.asarray(f["original_ltv"], dtype=np.float64)[rows],
                dti=np.asarray(f["original_dti"], dtype=np.float64)[rows],
                original_upb=np.exp(np.asarray(f["log_original_upb"], dtype=np.float64)[rows]),
            )
            prepay, _, _ = outcome_probabilities(state)
            total += float(prepay.sum())
        smm = total / reference.rows
        out.append({"incentive_bps": value, "smm": smm, "cpr": float(cpr_from_smm(smm))})
    return out


def bin_support(train: PanelBatch) -> list[dict[str, Any]]:
    """Training rows and payoffs per B1 incentive bin (the lookup's evidence per column)."""
    incentive = np.nan_to_num(np.asarray(train.features["incentive_bps"], dtype=np.float64))
    bins = np.searchsorted(np.asarray(INCENTIVE_EDGES), incentive, side="right")
    edges: list[float] = [-np.inf, *INCENTIVE_EDGES, np.inf]
    out = []
    for b in range(len(INCENTIVE_EDGES) + 1):
        mask = bins == b
        within = incentive[mask]
        out.append(
            {
                "bin": f"[{edges[b]:g}, {edges[b + 1]:g})",
                "rows": int(mask.sum()),
                "payoffs": int((train.outcome_class[mask] == 1).sum()),
                "incentive_p05": float(np.quantile(within, 0.05)) if within.size else None,
                "incentive_p95": float(np.quantile(within, 0.95)) if within.size else None,
            }
        )
    return out


def shape_error(curve: list[dict[str, float]], truth: list[dict[str, float]]) -> FloatArray:
    """Model minus true CPR at each grid value (percentage points)."""
    return np.array([(c["cpr"] - t["cpr"]) * 100 for c, t in zip(curve, truth, strict=True)])


def investigate(
    run_dir: Path,
    data_root: Path,
    lock: DataLock,
    *,
    reference_fraction: float = 0.02,
    truth_dir: Path | None = None,
) -> dict[str, Any]:
    """Bin support on training rows and incentive response on Validation B rows (no test data)."""
    import duckdb

    from prepay import periods
    from prepay.modeling.registry import load_run
    from prepay.modeling.windows import read_window, standard_windows
    from prepay.transform import warehouse_path

    run = load_run(run_dir)
    windows = {
        w.name: w for w in standard_windows(periods.parse_iso(lock.performance_cutoff_month))
    }
    fraction = run.manifest["training_config"]["train_sample_fraction"]
    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
        train = read_window(con, windows["train"], sample_fraction=fraction)
        support = bin_support(train)
        del train
        reference = read_window(con, windows["validation_b"], sample_fraction=reference_fraction)
    models = {n: run.models[n] for n in ("B1_lookup", "B2_logistic", "M1_lightgbm")}
    report: dict[str, Any] = {
        "run_id": run.manifest["run_id"],
        "synthetic": run.manifest["synthetic"],
        "train_sample_fraction": fraction,
        "reference": f"validation_b, loan-hash fraction {reference_fraction}",
        "b1_incentive_bin_support": support,
        "response": incentive_response(models, reference),
    }
    if truth_dir is not None:
        truth = true_incentive_response(reference)
        report["true_response"] = truth
        report["shape_error_pp"] = {
            name: shape_error(curve, truth).round(3).tolist()
            for name, curve in report["response"]["curves"].items()
        }
    return report


# --------------------------------------------------------------------------- reliability program
def diagnose_run(
    run_dir: Path,
    data_root: Path,
    lock: DataLock,
    *,
    reference_fraction: float = 0.02,
    allow_opened: bool = False,
) -> tuple[dict[str, Any], Any]:
    """D1 era encoding, D2 probes and D3 support map for a run (RELIABILITY_PLAN §6).

    Probes use the run's own calibration window: Validation B for a primary run, the calibrate
    window for an experiment run. Support maps read feature columns only, on every window. The
    second return value is the run's :class:`~prepay.reliability.support.SupportProfile`.
    """
    import duckdb

    from prepay import periods
    from prepay.features.derived import augment
    from prepay.features.panel import rate_path_from_warehouse, read_features
    from prepay.modeling.experiment import evidence_class
    from prepay.modeling.probes import era_encoding, probe_models
    from prepay.modeling.registry import load_run, training_sample
    from prepay.modeling.windows import Window, read_window, standard_windows
    from prepay.reliability.support import MONITORED, SupportProfile
    from prepay.transform import warehouse_path

    run = load_run(run_dir)
    manifest = run.manifest
    primary = manifest.get("kind", "prepay-model-run") == "prepay-model-run"
    reference_json = manifest["windows"]["validation_b" if primary else "calibrate"]
    reference_window = Window(
        "reference",
        "validation",
        periods.parse_iso(reference_json["first"]),
        periods.parse_iso(reference_json["last"]),
    )
    evidence = evidence_class(lock, reference_window.last, allow_opened=allow_opened)
    fraction, index = training_sample(manifest)
    train_window = Window(
        "train", "train", 0, periods.parse_iso(manifest["windows"]["train"]["last"])
    )
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
        rates = rate_path_from_warehouse(con)
        train = augment(
            read_window(con, train_window, sample_fraction=fraction, sample_index=index), rates
        )
        reference = augment(
            read_window(con, reference_window, sample_fraction=reference_fraction), rates
        )
        windows = {
            w.name: read_features(
                con, w.first, w.last, MONITORED, sample_fraction=reference_fraction
            )
            for w in standard_windows(cutoff)
            if w.name != "train"
        }
    profile = SupportProfile.fit(train.features, train.outcome_class)
    era = era_encoding(train)
    train_rows = train.rows
    del train
    models = {name: run.calibrated(name) for name in run.models}
    probes = probe_models(models, reference, manifest.get("feature_support"))
    support_map = {
        name: profile.assess(features)
        for name, features in windows.items()
        if features[MONITORED[0]].shape[0]
    }
    report = {
        "kind": "prepay-run-diagnostics",
        "run_id": manifest["run_id"],
        "synthetic": manifest["synthetic"],
        "evidence_class": evidence,
        "reference": f"{reference_window.label}, loan-hash fraction {reference_fraction}",
        "reference_rows": reference.rows,
        "training_rows": train_rows,
        "d1_era_encoding": era,
        "d2_probes": probes,
        "d3_support_map": {
            "note": "feature columns only (no outcomes); loan-hash fraction "
            f"{reference_fraction} of each window",
            "windows": support_map,
        },
        "flags": {
            "era_proxies": era.get("flagged", []),
            "models": probes["flags"],
            "windows_not_supported": sorted(
                name for name, s in support_map.items() if s["verdict"] != "supported"
            ),
        },
    }
    return report, profile


def stability(
    data_root: Path,
    lock: DataLock,
    out_root: Path,
    *,
    kind: str,
    base: ExperimentConfig,
    replicates: int = 5,
    reference_fraction: float = 0.02,
) -> Path:
    """D6 (``kind="samples"``: disjoint loan samples) or D7 (``"seeds"``: LightGBM seeds).

    Each replicate refits ``base``'s families on its windows. Tune-window log loss and the
    incentive response on one fixed reference sample are compared across replicates.
    """
    import dataclasses
    import datetime as dt

    import duckdb

    from prepay.features.derived import augment
    from prepay.features.panel import rate_path_from_warehouse
    from prepay.io import read_json, write_json_atomic
    from prepay.modeling.experiment import run_experiment
    from prepay.modeling.lockbox import read_only
    from prepay.modeling.probes import PROBES, probe_models, stability_summary
    from prepay.modeling.registry import load_run
    from prepay.modeling.windows import Window, read_window
    from prepay.transform import warehouse_path

    if kind not in ("samples", "seeds"):
        raise ValueError("kind must be 'samples' or 'seeds'")
    if kind == "samples" and base.train_sample_fraction is None:
        raise ValueError("sample stability needs a training sample fraction")
    first, last = base.windows.calibrate
    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
        reference = augment(
            read_window(
                con,
                Window("reference", "validation", first, last),
                sample_fraction=reference_fraction,
            ),
            rate_path_from_warehouse(con),
        )
    incentive = next(p for p in PROBES if p.name == "incentive")
    losses: dict[str, list[float]] = {name: [] for name in base.models}
    curves: dict[str, list[list[float]]] = {name: [] for name in base.models}
    runs = []
    for k in range(replicates):
        config = dataclasses.replace(
            base,
            experiment_id=f"{'D6' if kind == 'samples' else 'D7'}-{k}",
            sample_index=k if kind == "samples" else base.sample_index,
            seed=None if kind == "samples" else 20261028 + k,
        )
        run_dir = run_experiment(data_root, lock, out_root, config)
        runs.append(run_dir.name)
        validation = read_json(run_dir / "validation.json")
        run = load_run(run_dir)
        probed = probe_models(
            {name: run.calibrated(name) for name in base.models}, reference, None
        )["probes"]["incentive"]["models"]
        for name in base.models:
            losses[name].append(float(validation[name]["tune"]["log_loss"]))
            curves[name].append(probed[name]["mean_smm"])
    report = {
        "kind": f"prepay-stability-{kind}",
        "evidence_class": "synthetic" if lock.synthetic else "development",
        "replicates": replicates,
        "runs": runs,
        "incentive_grid": list(incentive.grid),
        "reference_rows": reference.rows,
        **stability_summary(losses, curves),
    }
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = out_root / f"stability-{kind}-{stamp}.json"
    write_json_atomic(target, report)
    read_only(target)
    return target
