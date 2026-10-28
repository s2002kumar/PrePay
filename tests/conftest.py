"""Shared pytest configuration. Every test is offline, synthetic and deterministic."""

from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

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
