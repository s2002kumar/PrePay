"""Training, holdout guard, seal and one-shot lockbox on the synthetic pipeline, plus the M0
end-to-end path: ingest -> dbt -> trained model -> finance projection."""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import duckdb
import numpy as np
import pytest

from prepay import periods
from prepay.features import compute_features
from prepay.features.panel import PanelBatch, load_statics, rate_path_from_bronze
from prepay.finance import (
    CreditAssumptions,
    HazardPaths,
    LoanLines,
    conservation_residuals,
    project,
)
from prepay.ingest.lock import DataLock
from prepay.io import read_json
from prepay.modeling import windows as windows_module
from prepay.modeling.lockbox import LockboxError, SealError, evaluate_lockbox, load_seal, seal
from prepay.modeling.registry import load_run
from prepay.modeling.train import TrainingConfig, train
from prepay.modeling.windows import HoldoutAccessError, read_window, standard_windows
from prepay.transform import warehouse_path

FAST = TrainingConfig(
    logistic_c_grid=(0.1,), gbm_num_leaves_grid=(7,), gbm_max_rounds=80, bootstrap_replicates=50
)


@pytest.fixture(scope="module")
def trained(
    built: tuple[Path, DataLock], tiny_dataset: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[Path, list[tuple[int, int]]]:
    root, lock = built
    requested: list[tuple[int, int]] = []
    original = windows_module.read_panel

    def spy(con: duckdb.DuckDBPyConnection, first: int, last: int, **kwargs: object) -> PanelBatch:
        requested.append((first, last))
        return original(con, first, last, **kwargs)  # type: ignore[arg-type]

    windows_module.read_panel = spy  # type: ignore[assignment]
    try:
        run_dir = train(
            root, lock, tmp_path_factory.mktemp("runs"), FAST, truth_dir=tiny_dataset / "truth"
        )
    finally:
        windows_module.read_panel = original
    return run_dir, requested


def test_training_never_reads_test_months(trained: tuple[Path, list[tuple[int, int]]]) -> None:
    _, requested = trained
    assert requested
    assert max(last for _, last in requested) == periods.month(2019, 12)


def test_run_manifest_records_provenance_and_selection(
    trained: tuple[Path, list[tuple[int, int]]], built: tuple[Path, DataLock]
) -> None:
    run_dir, _ = trained
    manifest = read_json(run_dir / "run-manifest.json")
    assert manifest["synthetic"] is True
    assert manifest["data_lock_fingerprint"] == built[1].fingerprint()
    for key in ("feature_contract_digest", "software_lock_digest", "windows", "tuning"):
        assert manifest[key]
    assert manifest["selection"]["selected"] in {"B1_lookup", "B2_logistic", "M1_lightgbm"}
    assert set(manifest["models"]) == {"B0_psa", "B1_lookup", "B2_logistic", "M1_lightgbm"}
    validation = read_json(run_dir / "validation.json")
    assert "not evidence of real accuracy" in validation["_truth_recovery"]["note"]
    assert not list(run_dir.rglob("*.pkl"))  # artifacts are JSON / LightGBM text only


def test_reloaded_run_predicts_identically(
    trained: tuple[Path, list[tuple[int, int]]], built: tuple[Path, DataLock]
) -> None:
    run_dir, _ = trained
    root, lock = built
    w = {x.name: x for x in standard_windows(periods.parse_iso(lock.performance_cutoff_month))}
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        batch = read_window(con, w["validation_b"])
    first, second = load_run(run_dir), load_run(run_dir)
    for name in first.models:
        np.testing.assert_array_equal(
            first.models[name].predict_proba(batch), second.models[name].predict_proba(batch)
        )


def test_test_windows_require_a_seal(built: tuple[Path, DataLock]) -> None:
    root, lock = built
    test_a = {
        x.name: x for x in standard_windows(periods.parse_iso(lock.performance_cutoff_month))
    }["test_a"]
    with (
        duckdb.connect(str(warehouse_path(root)), read_only=True) as con,
        pytest.raises(HoldoutAccessError, match="sealed holdout"),
    ):
        read_window(con, test_a)


def _assert_adr_0006_sections(report: dict) -> None:
    """Segment tables, credit gating and balance run-off are present and internally consistent."""
    from prepay.evaluation.segments import DIMENSIONS

    credit = report["credit_sufficiency"]
    assert set(credit["credit_events"]) == {"train", "validation_a", "validation_b"}
    for result in report["results"].values():
        assert set(result["_segments"]["dimensions"]) == {d.name for d in DIMENSIONS}
        interpretable = result["_credit"]["metrics_interpretable"]
        assert interpretable == (
            credit["credit_hazard_validated"] and result["_credit"]["credit_events"] >= 100
        )
        rows = sum(
            cell["rows"]
            for cell in result["_segments"]["dimensions"]["loan_age_months"].values()
            if "rows" in cell
        )
        assert rows <= result["selected"]["rows"]
    runoff = report["runoff_backtests"]
    assert set(runoff) == {"2019-12", "2021-12", "2023-12"}
    for entry in runoff.values():
        assert entry["observation_gaps_loan_months"] == 0
        observed = entry["observed"]
        factor = observed["pool_factor"]["24m"]
        interval = observed["pool_factor_interval_at_horizon"]
        assert 0.0 < factor <= 1.0
        assert interval["low"] <= factor <= interval["high"]
        parts = observed["cumulative_principal_fraction"]
        returned = sum(parts[p]["24m"] for p in ("payoff", "credit_exit", "amortization"))
        assert returned == pytest.approx(1.0 - factor, abs=1e-9)  # observed balance telescopes
        for modes in entry["models"].values():
            for result in modes.values():
                projected = result["pool_factor"]["24m"]
                parts = result["cumulative_principal_fraction"]
                returned = sum(parts[p]["24m"] for p in ("payoff", "credit_exit", "amortization"))
                assert returned == pytest.approx(1.0 - projected, abs=1e-9)
                assert 0.0 < result["wal_truncated_years"] <= 2.0


def test_seal_and_one_shot_lockbox(
    trained: tuple[Path, list[tuple[int, int]]], built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    run_dir = tmp_path / "run"
    shutil.copytree(trained[0], run_dir)
    with pytest.raises(SealError, match="not sealed"):
        evaluate_lockbox(run_dir, root, lock)
    sealed = seal(run_dir)
    with pytest.raises(SealError, match="write-once"):
        seal(run_dir)
    report = evaluate_lockbox(run_dir, root, lock)
    assert report["candidate_digest"] == sealed.payload["candidate_digest"]
    assert set(report["results"]) == {"test_a", "test_b", "test_c"}
    for result in report["results"].values():
        assert {"B1_lookup", "B2_logistic", "M1_lightgbm", "selected"} <= set(result)
        assert set(result["_flags"]["gbm_vs_baselines"]) == {"B1_lookup", "B2_logistic"}
    cohorts = report["cohort_backtests"]
    assert set(cohorts) == {"2019-12", "2021-12", "2023-12"}
    for cohort in cohorts.values():
        assert cohort["cohort_loans"] > 50
        for entry in cohort["horizons"].values():
            assert 0.0 <= entry["realized_aalen_johansen_prepay"] <= 1.0
            low, high = (
                entry["realized_prepay_interval"]["low"],
                entry["realized_prepay_interval"]["high"],
            )
            assert low <= entry["realized_aalen_johansen_prepay"] <= high
            assert set(entry["models"]["selected"]) == {"hindsight_rates", "as_of_flat_rates"}
        bounds = cohort["censoring_sensitivity"]["prepay_incidence"]
        assert (
            bounds["bound_censored_never_pay_off"]
            <= bounds["aalen_johansen"]
            <= bounds["bound_censored_all_pay_off"]
        )
    _assert_adr_0006_sections(report)
    with pytest.raises(LockboxError, match="immutable"):
        evaluate_lockbox(run_dir, root, lock)


def test_tampering_after_seal_is_detected(
    trained: tuple[Path, list[tuple[int, int]]], built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    run_dir = tmp_path / "run"
    shutil.copytree(trained[0], run_dir)
    seal(run_dir)
    target = run_dir / "models" / "B1_lookup.json"
    target.write_text(target.read_text(encoding="utf-8").replace("0.", "0.0", 1), encoding="utf-8")
    with pytest.raises(SealError, match="changed after sealing"):
        load_seal(run_dir)
    with pytest.raises(SealError):
        evaluate_lockbox(run_dir, root, lock)


def test_lockbox_refuses_a_different_data_lock(
    trained: tuple[Path, list[tuple[int, int]]], built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    run_dir = tmp_path / "run"
    shutil.copytree(trained[0], run_dir)
    seal(run_dir)
    other = dataclasses.replace(lock, terms_reference="different")
    with pytest.raises(LockboxError, match="data lock"):
        evaluate_lockbox(run_dir, root, other)


def test_end_to_end_model_hazards_drive_a_conserving_projection(
    trained: tuple[Path, list[tuple[int, int]]], built: tuple[Path, DataLock]
) -> None:
    """SPEC M0: synthetic ingest -> transform -> trained model -> finance projection."""
    root, lock = built
    run = load_run(trained[0])
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        _, statics = load_statics(con)
    rates = rate_path_from_bronze(root / "bronze")
    t0 = periods.parse_iso(lock.performance_cutoff_month)
    horizon = 24
    alive = np.flatnonzero(statics.maturity_month > t0 + horizon)[:50]
    path = rates.extended(
        np.full(horizon, rates.rate_30y[-1]), np.full(horizon, rates.rate_15y[-1])
    )
    loan_index = np.repeat(alive, horizon)
    months = np.tile(np.arange(t0 + 1, t0 + horizon + 1), alive.size)
    features = compute_features(statics, path, loan_index, months)
    batch = PanelBatch(
        loan_id=np.array(loan_index, dtype=object),
        target_month=months,
        outcome_class=np.zeros(months.size, dtype=np.int64),
        exposure_upb=np.zeros(months.size),
        features=features,
    )
    p = run.selected.predict_proba(batch).reshape(alive.size, horizon, 3)
    hazards = HazardPaths(prepay=p[:, :, 1], credit=p[:, :, 2], active=p[:, :, 0])
    lines = LoanLines.from_values(
        statics.original_upb[alive] * 0.8,
        statics.note_rate_pct[alive] / 100.0,
        statics.maturity_month[alive] - t0,
    )
    ledger = project(
        lines, hazards, CreditAssumptions(severity=0.35, recovery_lag_months=12), horizon
    ).pool
    assert conservation_residuals(ledger).ok
    assert ledger.voluntary_prepay_principal.sum() > 0
    assert ledger.ending_upb[-1] < ledger.beginning_upb[0]
