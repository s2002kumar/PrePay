"""Shared pytest configuration. Every test is offline, synthetic and deterministic."""

from __future__ import annotations

import os
import pathlib

import pytest
from hypothesis import HealthCheck, settings

from prepay.synthetic.config import SyntheticConfig
from prepay.synthetic.dataset import generate_dataset

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
#: Small multi-block dataset spanning every MODELING §5 window (2015..2026, cutoff 2026-06).
TINY_CONFIG = SyntheticConfig(
    seed=11, first_vintage=2015, last_vintage=2026, loans_per_vintage=60, block_size=25
)


@pytest.fixture(scope="session")
def tiny_dataset(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """A generated synthetic source dataset shared (read-only) by integration tests."""
    root = tmp_path_factory.mktemp("synthetic")
    generate_dataset(TINY_CONFIG, root)
    return root
