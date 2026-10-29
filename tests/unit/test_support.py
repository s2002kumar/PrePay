"""Applicability monitor (R1, ADR 0009 §7): row status, PSI and verdict thresholds."""

from __future__ import annotations

import json

import numpy as np
import pytest

from prepay.reliability.support import (
    OUTSIDE,
    SPARSE,
    SUPPORTED,
    PsiBins,
    SupportProfile,
)


def _features(n: int, seed: int, *, shift: float = 0.0) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    return {
        "incentive_bps": rng.normal(20 + shift, 60, n),
        "market_rate_t1": rng.uniform(3.5, 6.5, n),
        "rate_change_6m_bps": rng.normal(0, 30, n),
        "loan_age": rng.integers(1, 150, n).astype(float),
        "burnout_months": rng.integers(0, 40, n).astype(float),
    }


@pytest.fixture(scope="module")
def profile() -> SupportProfile:
    features = _features(400_000, 1)
    rng = np.random.default_rng(2)
    outcome = (rng.random(400_000) < 0.01).astype(np.int64)
    return SupportProfile.fit(features, outcome)


def _rows(**values: float) -> dict[str, np.ndarray]:
    base = {
        "incentive_bps": 20.0,
        "market_rate_t1": 5.0,
        "rate_change_6m_bps": 0.0,
        "loan_age": 40.0,
        "burnout_months": 5.0,
    }
    return {k: np.array([values.get(k, v)]) for k, v in base.items()}


def test_rows_are_supported_sparse_or_outside(profile: SupportProfile) -> None:
    assert profile.row_status(_rows())[0] == SUPPORTED
    assert profile.row_status(_rows(incentive_bps=-400.0))[0] == OUTSIDE
    assert profile.row_status(_rows(market_rate_t1=2.8))[0] == OUTSIDE
    # Inside every univariate range, but the joint cells hold fewer than 20 training payoffs.
    assert profile.bounds["incentive_bps"][0] < -120.0
    assert profile.row_status(_rows(incentive_bps=-120.0, market_rate_t1=3.6))[0] == SPARSE


def test_verdict_follows_the_preregistered_thresholds(profile: SupportProfile) -> None:
    same = profile.assess(_features(50_000, 3))
    assert same["verdict"] == "supported"
    assert all(v < 0.01 for v in same["psi"].values())
    shifted = profile.assess(_features(50_000, 4, shift=-250.0))
    assert shifted["verdict"] == "unsupported"
    assert shifted["outside_share"] >= 0.25
    assert "incentive_bps outside training range" in shifted["reasons"]
    mild = profile.assess(_features(50_000, 5, shift=-60.0))
    assert mild["verdict"] == "extrapolating"


def test_projections_are_judged_on_rows_not_population_mix(profile: SupportProfile) -> None:
    """A pool of identical supported lines has a huge PSI but is fully supported."""
    pool = {k: np.repeat(v, 500) for k, v in _rows().items()}
    population = profile.assess(pool)
    projection = profile.assess(pool, weights=np.full(500, 2.0e5), population=False)
    assert population["verdict"] == "extrapolating"  # PSI flags the mix
    assert projection["verdict"] == "supported"
    assert projection["psi"] == {}
    assert projection["weighting"] == "balance"


def test_balance_weights_drive_the_shares(profile: SupportProfile) -> None:
    rows = {k: np.concatenate([_rows()[k], _rows(incentive_bps=-500.0)[k]]) for k in _rows()}
    light = profile.assess(rows, weights=np.array([99.0, 1.0]), population=False)
    heavy = profile.assess(rows, weights=np.array([1.0, 99.0]), population=False)
    assert light["outside_share"] == pytest.approx(0.01)
    assert light["verdict"] == "supported"
    assert heavy["verdict"] == "unsupported"


def test_psi_is_zero_for_identical_shares_and_grows_with_shift() -> None:
    rng = np.random.default_rng(7)
    reference = rng.normal(0, 1, 100_000)
    bins = PsiBins.fit(reference)
    assert bins.psi(rng.normal(0, 1, 100_000)) == pytest.approx(0.0, abs=0.01)
    assert bins.psi(rng.normal(1, 1, 100_000)) > 0.25
    assert bins.psi(np.array([np.nan])) is None


def test_profile_round_trips_through_json(profile: SupportProfile) -> None:
    payload = json.loads(json.dumps(profile.to_json()))
    restored = SupportProfile.from_json(payload)
    rows = _features(2_000, 9, shift=-120.0)
    np.testing.assert_array_equal(restored.row_status(rows), profile.row_status(rows))
    assert restored.assess(rows) == profile.assess(rows)
