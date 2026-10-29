"""Run diagnostics (D1-D3) and stability (D6) on the synthetic pipeline (ADR 0009 §6)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import duckdb
import pytest

from prepay import periods
from prepay.features.panel import PanelBatch, read_features
from prepay.ingest.lock import DataLock
from prepay.modeling import windows as windows_module
from prepay.modeling.diagnostics import diagnose_run, stability
from prepay.modeling.experiment import ExperimentConfig, preset
from prepay.modeling.train import TrainingConfig, train
from prepay.reliability.support import SupportProfile
from prepay.transform import warehouse_path

FAST = TrainingConfig(logistic_c_grid=(0.1,), gbm_num_leaves_grid=(7,), gbm_max_rounds=60)


@pytest.fixture(scope="module")
def primary_run(built: tuple[Path, DataLock], tmp_path_factory: pytest.TempPathFactory) -> Path:
    root, lock = built
    return train(root, lock, tmp_path_factory.mktemp("runs"), FAST)


def test_diagnostics_read_outcomes_only_through_2019(
    primary_run: Path, built: tuple[Path, DataLock]
) -> None:
    root, lock = built
    requested: list[tuple[int, int]] = []
    original = windows_module.read_panel

    def spy(con: duckdb.DuckDBPyConnection, first: int, last: int, **kwargs: object) -> PanelBatch:
        requested.append((first, last))
        return original(con, first, last, **kwargs)  # type: ignore[arg-type]

    windows_module.read_panel = spy  # type: ignore[assignment]
    try:
        report, profile = diagnose_run(primary_run, root, lock, reference_fraction=0.5)
    finally:
        windows_module.read_panel = original
    assert max(last for _, last in requested) == periods.month(2019, 12)

    assert report["evidence_class"] == "synthetic"
    assert set(report["d2_probes"]["probes"]) >= {"incentive", "rate_level_at_fixed_incentive"}
    assert set(report["d2_probes"]["flags"]) == {
        "B0_psa",
        "B1_lookup",
        "B2_logistic",
        "M1_lightgbm",
    }
    support = report["d3_support_map"]["windows"]
    assert {"validation_b", "test_a", "test_b", "test_c"} <= set(support)
    assert all(
        w["verdict"] in ("supported", "extrapolating", "unsupported") for w in support.values()
    )
    assert "market_rate_t1" in report["d1_era_encoding"]["features"]
    restored = SupportProfile.from_json(json.loads(json.dumps(profile.to_json())))
    assert restored.training_rows == report["training_rows"]


def test_feature_reader_refuses_outcome_and_identifier_columns(
    built: tuple[Path, DataLock],
) -> None:
    root, _ = built
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        for column in ("outcome_class", "loan_id", "exposure_upb", "term_bucket"):
            with pytest.raises(ValueError, match="numeric feature"):
                read_features(con, 0, periods.month(2030, 1), (column,))
        values = read_features(con, periods.month(2020, 1), periods.month(2026, 6), ("loan_age",))
    assert values["loan_age"].size > 0


def test_sample_stability_refits_disjoint_samples(
    built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    base = ExperimentConfig(
        "D6",
        preset("DEV2017", periods.month(2026, 6)).windows,
        ("B2_logistic", "M1_lightgbm"),
        designated="B2_logistic",
        train_sample_fraction=0.4,
        logistic_c_grid=(0.1,),
        gbm_num_leaves_grid=(7,),
        gbm_max_rounds=60,
    )
    target = stability(root, lock, tmp_path, kind="samples", base=base, replicates=2)
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["kind"] == "prepay-stability-samples"
    assert len(report["runs"]) == 2
    for family in ("B2_logistic", "M1_lightgbm"):
        assert len(report["families"][family]["tune_log_loss"]) == 2
        assert isinstance(report["families"][family]["unstable"], bool)
    with pytest.raises(ValueError, match="fraction"):
        stability(
            root,
            lock,
            tmp_path,
            kind="samples",
            base=dataclasses.replace(base, train_sample_fraction=None),
        )
