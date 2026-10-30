"""Experiment runs and rolling-origin folds on the synthetic pipeline (ADR 0009, ADR 0010)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pytest

from prepay import periods
from prepay.features.derived import augment
from prepay.features.panel import PanelBatch, rate_path_from_warehouse, read_panel
from prepay.ingest.lock import DataLock
from prepay.io import read_json
from prepay.modeling import windows as windows_module
from prepay.modeling.experiment import (
    DEVELOPMENT_REPORT,
    ExperimentConfig,
    OpenedWindowError,
    evidence_class,
    preset,
    rolling_origin,
    run_experiment,
)
from prepay.modeling.lockbox import LockboxError, evaluate_lockbox, seal
from prepay.modeling.models import TemperatureCalibrated
from prepay.modeling.registry import load_run
from prepay.modeling.windows import Window, read_window
from prepay.transform import warehouse_path

FAST = {
    "logistic_c_grid": (0.1,),
    "gbm_num_leaves_grid": (7,),
    "gbm_max_rounds": 60,
    "hazard_l2_grid": (1e-3,),
}


def _fast(config: ExperimentConfig, **changes: object) -> ExperimentConfig:
    return dataclasses.replace(config, **FAST, **changes)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def dev_run(built: tuple[Path, DataLock], tmp_path_factory: pytest.TempPathFactory) -> Path:
    root, lock = built
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    config = _fast(preset("DEV2017", cutoff))
    return run_experiment(root, lock, tmp_path_factory.mktemp("experiments"), config)


def test_member_run_records_provenance_and_per_model_calibration(dev_run: Path) -> None:
    manifest = read_json(dev_run / "run-manifest.json")
    assert manifest["kind"] == "prepay-experiment-run"
    assert manifest["evidence_class"] == "synthetic"
    assert manifest["experiment_id"] == "DEV2017"
    for key in ("git_sha", "software_lock_digest", "duckdb_version", "config_digest"):
        assert manifest[key]
    assert "git_dirty" in manifest
    assert manifest["training_sample"]["index"] == 0
    models = {"X1_factored_gbm", "X2_factored_gbm", "X3_factored_gbm", "H1_constrained_hazard"}
    assert set(manifest["models"]) == models
    assert set(manifest["calibration"]) == models
    assert manifest["selection"]["selected"] == "X2_factored_gbm"
    assert manifest["windows"]["calibrate"] == {
        "role": "validation",
        "first": "2019-01",
        "last": "2019-12",
    }
    for name in models:  # monotone constraints hold on real panel rows, not just toy data
        assert manifest["monotonicity"][name]["payoff_hazard_falls_with_incentive"] == 0.0
    for name in models - {"X1_factored_gbm"}:
        assert manifest["monotonicity"][name]["payoff_hazard_rises_with_burnout"] == 0.0
    assert not list(dev_run.rglob("*.pkl"))


def test_member_run_reloads_and_scores_with_its_own_calibration(
    dev_run: Path, built: tuple[Path, DataLock]
) -> None:
    root, _ = built
    run = load_run(dev_run)
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        rates = rate_path_from_warehouse(con)
        batch = augment(
            read_window(
                con, Window("v", "validation", periods.month(2019, 1), periods.month(2019, 6))
            ),
            rates,
        )
    for name in run.models:
        model = run.calibrated(name)
        adopted = run.manifest["calibration"][name]["adopted"]
        assert isinstance(model, TemperatureCalibrated) == adopted
        p = model.predict_proba(batch)
        np.testing.assert_allclose(p.sum(axis=1), 1.0, atol=1e-12)
        np.testing.assert_array_equal(p, load_run(dev_run).calibrated(name).predict_proba(batch))


def test_member_runs_seal_for_forward_use_but_refuse_the_lockbox(
    dev_run: Path, built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    copy = tmp_path / dev_run.name
    import shutil

    shutil.copytree(dev_run, copy)
    sealed = seal(copy)
    assert "ADR 0010" in sealed.payload["evaluation_plan"]["protocol"]
    assert sealed.payload["report_flags"] is None
    with pytest.raises(LockboxError, match="forward months"):
        evaluate_lockbox(copy, root, lock)


def test_opened_months_need_the_explicit_exploratory_flag(
    built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    with pytest.raises(OpenedWindowError, match="exploratory"):
        run_experiment(root, lock, tmp_path, _fast(preset("REFIT2026", cutoff)))
    assert not list(tmp_path.iterdir())  # refused before anything was read or written
    real = SimpleNamespace(performance_cutoff_month="2026-06", synthetic=False)
    assert evidence_class(real, periods.month(2019, 12), allow_opened=False) == "development"  # type: ignore[arg-type]
    assert (
        evidence_class(real, periods.month(2026, 6), allow_opened=True)  # type: ignore[arg-type]
        == "exploratory-opened-window"
    )
    with pytest.raises(ValueError, match="cutoff"):
        evidence_class(real, periods.month(2026, 7), allow_opened=True)  # type: ignore[arg-type]


def test_rolling_origin_reads_development_months_only(
    built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    requested: list[tuple[int, int]] = []
    original = windows_module.read_panel

    def spy(con: duckdb.DuckDBPyConnection, first: int, last: int, **kwargs: object) -> PanelBatch:
        requested.append((first, last))
        return original(con, first, last, **kwargs)  # type: ignore[arg-type]

    base = _fast(
        ExperimentConfig(
            "V1",
            preset("DEV2017", periods.month(2026, 6)).windows,
            ("B2_logistic", "M1_lightgbm", "X2_factored_gbm", "H1_constrained_hazard"),
            designated="B2_logistic",
        )
    )
    windows_module.read_panel = spy  # type: ignore[assignment]
    try:
        report_path = rolling_origin(
            root,
            lock,
            tmp_path,
            base,
            origins=(periods.month(2007, 12), periods.month(2015, 12)),
        )
    finally:
        windows_module.read_panel = original
    assert max(last for _, last in requested) <= periods.month(2019, 12)

    summary = json.loads(report_path.read_text(encoding="utf-8"))
    assert summary["evidence_class"] == "synthetic"
    assert "skipped" in summary["folds"]["2007-12"]  # the data starts in 2006: no training rows
    fold = summary["folds"]["2015-12"]
    assert fold["window"] == "2016-01..2017-12"
    assert set(fold["models"]) == set(base.models)
    aggregate = summary["aggregate"]
    assert sum(entry["wins"] for entry in aggregate.values()) == 1
    assert "vs_B2_logistic" in aggregate["M1_lightgbm"]

    report = read_json(tmp_path / summary["runs"]["2015-12"] / DEVELOPMENT_REPORT)
    assert report["evidence_class"] == "synthetic"
    for horizon in report["cohort_attribution"]["horizons"].values():
        for errors in horizon["models"].values():
            total = errors["behavioral_error_pp"] + errors["rate_path_error_pp"]
            assert total == pytest.approx(errors["total_error_pp"], abs=1e-9)
    regime = report["regime_calibration"]["B2_logistic"]["dimensions"]
    assert set(regime) == {"rate_level_band", "rate_change_6m", "new_low"}


def test_disjoint_samples_share_no_loan(built: tuple[Path, DataLock]) -> None:
    root, _ = built
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        first = read_panel(con, 0, periods.month(2017, 12), sample_fraction=0.25, sample_index=0)
        second = read_panel(con, 0, periods.month(2017, 12), sample_fraction=0.25, sample_index=1)
        legacy = read_panel(con, 0, periods.month(2017, 12), sample_fraction=0.25)
    assert first.rows
    assert second.rows
    assert not set(first.loan_id) & set(second.loan_id)
    np.testing.assert_array_equal(first.loan_id, legacy.loan_id)  # index 0 = the primary sample


def test_verification_reports_boolean_invariants_only(
    dev_run: Path, built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    from prepay.modeling.verify import verify_run

    root, lock = built
    copy = tmp_path / dev_run.name
    import shutil

    shutil.copytree(dev_run, copy)
    # A developer's dirty tree makes clean_code fail by design; CI checks out clean code.
    dirty = read_json(copy / "run-manifest.json")["git_dirty"] is not False
    expected_dirty = {"clean_code"} if dirty else set()
    unsealed = verify_run(copy, root, lock, preset_name="DEV2017")
    assert set(unsealed["failed"]) == {"seal_intact"} | expected_dirty
    seal(copy)
    report = verify_run(copy, root, lock, preset_name="DEV2017")
    assert set(report["failed"]) == expected_dirty, report["failed"]
    for name in ("X1_factored_gbm", "X2_factored_gbm", "X3_factored_gbm", "H1_constrained_hazard"):
        assert report["checks"][f"{name}.level_invariant"] is True
        assert report["checks"][f"{name}.hazard_monotone_incentive"] is True
    assert "X1_factored_gbm.hazard_monotone_burnout" not in report["checks"]
    assert report["properties"]["H1_constrained_hazard.no_material_payoff_decrease"] is True
    assert all(
        isinstance(v, bool) for v in [*report["checks"].values(), *report["properties"].values()]
    )
    wrong = verify_run(copy, root, lock, preset_name="REFIT2026")
    assert {"preset_windows_match", "preset_models_match"} <= set(wrong["failed"])
