"""Interval methods for loan-month panels (ADR 0010 amendment 2): coverage under month shocks."""

from __future__ import annotations

import numpy as np
import pytest

from prepay.evaluation.inference import (
    coverage_study,
    loan_cluster,
    simulate_panel,
    summarize,
    two_way,
)


def test_loan_cluster_intervals_undercover_when_months_share_shocks() -> None:
    """The finding behind amendment 2, at CI scale (the full study is in FORWARD_AUDIT.md)."""
    common = {"loans": 600, "simulations": 120, "replicates": 150}
    calm = coverage_study(sd_month=0.0, **common)
    shocked = coverage_study(sd_month=0.3, **common)
    assert calm["coverage"]["loan_cluster"] >= 0.88
    assert calm["coverage"]["two_way"] >= 0.88
    assert shocked["coverage"]["loan_cluster"] < 0.7
    assert shocked["coverage"]["two_way"] >= 0.82
    assert shocked["mean_width"]["two_way"] > 2 * shocked["mean_width"]["loan_cluster"]


def test_simulated_panels_are_unbalanced_and_month_indexed() -> None:
    rng = np.random.default_rng(1)
    loans, months, values = simulate_panel(
        rng, loans=50, months=12, sd_loan=1.0, sd_month=0.5, sd_noise=1.0
    )
    assert loans.shape == months.shape == values.shape
    assert months.min() >= 0
    assert months.max() <= 11
    per_loan = np.bincount(loans)
    assert per_loan.min() >= 1
    assert per_loan.max() <= 12


def test_one_sided_p_measures_evidence_for_a_negative_mean() -> None:
    rng = np.random.default_rng(2)
    loans = np.repeat(np.arange(400), 6)
    months = np.tile(np.arange(6), 400)
    better = rng.normal(-0.05, 0.2, loans.size)
    draws = two_way(loans, months, better, replicates=300, seed=3)
    interval = summarize(draws, float(better.mean()), "two_way")
    assert interval.high < 0
    assert interval.p_one_sided < 0.01
    worse = summarize(
        loan_cluster(loans, -better, replicates=300, seed=3), float(-better.mean()), "loan"
    )
    assert worse.p_one_sided > 0.99
    assert interval.as_dict()["method"] == "two_way"


def test_two_way_resampling_is_seeded_and_reproducible() -> None:
    rng = np.random.default_rng(4)
    loans, months, values = simulate_panel(
        rng, loans=100, months=12, sd_loan=1.0, sd_month=0.2, sd_noise=1.0
    )
    a = two_way(loans, months, values, replicates=50, seed=9)
    b = two_way(loans, months, values, replicates=50, seed=9)
    np.testing.assert_array_equal(a, b)
    assert np.mean(a) == pytest.approx(values.mean(), abs=0.2)
