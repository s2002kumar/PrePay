"""Shared pytest configuration. Every test is offline, synthetic and deterministic."""

from __future__ import annotations

import os
import pathlib

import pytest
from hypothesis import HealthCheck, settings

from prepay.ingest import ingest_all
from prepay.ingest.lock import DataLock, create_lock
from prepay.synthetic.config import SyntheticConfig
from prepay.synthetic.dataset import generate_dataset
from prepay.transform import run_dbt

# "ci" (default) derandomizes Hypothesis so every run explores the same examples; use
# HYPOTHESIS_PROFILE=explore locally to search new random examples.
settings.register_profile(
    "ci",
    derandomize=True,
    max_examples=150,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile("explore", max_examples=2000, deadline=None, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


# --------------------------------------------------------------------------- synthetic data
#: Small multi-block dataset spanning every MODELING §5 window (2006..2026, cutoff 2026-06); the
#: training window includes the fictional 2008-2011 credit stress so every class occurs.
TINY_CONFIG = SyntheticConfig(
    seed=11, first_vintage=2006, last_vintage=2026, loans_per_vintage=80, block_size=30
)


@pytest.fixture(scope="session")
def tiny_dataset(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """A generated synthetic source dataset shared (read-only) by integration tests."""
    root = tmp_path_factory.mktemp("synthetic")
    generate_dataset(TINY_CONFIG, root)
    return root


@pytest.fixture(scope="session")
def built(
    tiny_dataset: pathlib.Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[pathlib.Path, DataLock]:
    root = tmp_path_factory.mktemp("pipeline")
    lock = create_lock(
        tiny_dataset / "raw",
        release=48,
        terms_reference="",
        synthetic_manifest=tiny_dataset / "manifest.json",
    )
    ingest_all(tiny_dataset / "raw", lock, root / "bronze")
    run_dbt(root, lock)
    return root, lock


@pytest.fixture(scope="session")
def demo_bundle(
    built: tuple[pathlib.Path, DataLock],
    tiny_dataset: pathlib.Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> pathlib.Path:
    """A verified demo bundle assembled from the tiny synthetic pipeline (fast settings)."""
    from prepay.api.bundle import assemble_bundle
    from prepay.modeling.lockbox import evaluate_lockbox, seal
    from prepay.modeling.train import TrainingConfig, train
    from prepay.reliability.support import profile_for_run

    root, lock = built
    config = TrainingConfig(logistic_c_grid=(0.1,), gbm_num_leaves_grid=(7,), gbm_max_rounds=80)
    run_dir = train(
        root, lock, tmp_path_factory.mktemp("demo-runs"), config, truth_dir=tiny_dataset / "truth"
    )
    seal(run_dir)
    evaluate_lockbox(run_dir, root, lock)
    return assemble_bundle(
        tmp_path_factory.mktemp("bundle") / "demo",
        run_dir,
        root / "bronze",
        preset="tiny",
        support_profile=profile_for_run(root, run_dir),
    )
