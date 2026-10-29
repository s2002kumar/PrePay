"""Reliability-program candidate families: coherence, constraints, invariances, round trips."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from prepay.features.batch import PanelBatch
from prepay.features.derived import DERIVED_NUMERIC
from prepay.features.spec import CATEGORICAL, NUMERIC
from prepay.modeling.challengers import (
    LEVEL_FEATURES,
    VARIANTS,
    ConstrainedHazard,
    FactoredGbm,
    _ramps,
    factored_probabilities,
    fit_logistic,
    ice_violation_share,
)
from prepay.modeling.design import Preprocessor
from prepay.modeling.models import IncoherentProbabilityError
from prepay.modeling.registry import load_run, save_models

CODES = {
    "term_bucket": ["15y", "30y"],
    "loan_purpose": ["P", "C", "N"],
    "occupancy_status": ["P", "I"],
    "channel": ["R", "C"],
    "first_time_homebuyer": ["Y", "N"],
    "property_type": ["SF", "CO"],
    "census_region": ["west", "south"],
    "month_of_year": list(range(1, 13)),
}


def make_world(n: int, seed: int) -> PanelBatch:
    """A small confounded world: an unobserved early-era turnover boost, and high rates early.

    Payoffs depend on incentive (S-curve), burnout and an era effect that the features don't
    carry. In this world the absolute rate level is a proxy for the era, as in the real
    training window (RELIABILITY_PLAN §3.1).
    """
    rng = np.random.default_rng(seed)
    early = rng.random(n) < 0.5
    features: dict[str, np.ndarray] = {name: rng.normal(0, 1, n) for name in NUMERIC}
    market = np.where(early, rng.uniform(5.6, 8.0, n), rng.uniform(3.3, 5.4, n))
    incentive = rng.normal(0, 110, n)
    features |= {
        "market_rate_t1": market,
        "incentive_bps": incentive,
        "note_rate_pct": market + incentive / 100,
        "loan_age": rng.integers(1, 200, n).astype(float),
        "burnout_months": rng.integers(0, 60, n).astype(float),
        "remaining_payments": rng.integers(60, 360, n).astype(float),
        "rate_change_6m_bps": rng.normal(0, 40, n),
        "sato_bps": rng.normal(30, 25, n),
        "credit_score": np.where(rng.random(n) < 0.03, np.nan, rng.normal(740, 40, n)),
        "original_ltv": rng.uniform(40, 97, n),
        "original_dti": rng.uniform(10, 50, n),
        "pmms_application_based": np.zeros(n),
        "new_opportunity_bps": np.maximum(rng.normal(-30, 40, n), -150),
        "new_low_bps": rng.normal(-40, 30, n),
        "payment_saving_pct": incentive / 12,
    }
    for name in CATEGORICAL:
        choices = CODES[name]
        features[name] = np.array(
            [choices[i] for i in rng.integers(0, len(choices), n)], dtype=object
        )
    refi = 2.2 / (1 + np.exp(-(incentive - 75) / 25))
    prepay = -5.0 + refi + 0.003 * np.minimum(incentive, 0) - 0.02 * features["burnout_months"]
    prepay += 0.9 * early
    credit = -6.5 + 0.03 * (features["original_ltv"] - 80)
    logits = np.column_stack([np.zeros(n), prepay, credit])
    p = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    u = rng.random(n)
    y = (u > p[:, 0]).astype(np.int64) + (u > p[:, 0] + p[:, 1]).astype(np.int64)
    return PanelBatch(
        loan_id=np.array([f"L{i // 10:06d}" for i in range(n)], dtype=object),
        target_month=np.where(early, 2004 * 12, 2014 * 12).astype(np.int64),
        outcome_class=y,
        exposure_upb=rng.uniform(5e4, 5e5, n),
        features=features,
    )


@pytest.fixture(scope="module")
def world() -> tuple[PanelBatch, PanelBatch, Preprocessor]:
    train, valid = make_world(40_000, 1), make_world(12_000, 2)
    return train, valid, Preprocessor.fit(train)


@pytest.fixture(scope="module")
def fitted(world: tuple[PanelBatch, PanelBatch, Preprocessor]) -> dict[str, object]:
    train, valid, pre = world
    models: dict[str, object] = {
        name: FactoredGbm.fit(train, valid, pre, variant=name, num_leaves=7, max_rounds=120)
        for name in VARIANTS
    }
    models["H1_constrained_hazard"] = ConstrainedHazard.fit(train, pre, l2=1e-3)
    return models


def _set(name: str):  # type: ignore[no-untyped-def]
    def setter(batch: PanelBatch, value: float) -> PanelBatch:
        return replace(batch, features={**batch.features, name: np.full(batch.rows, value)})

    return setter


def test_factored_probabilities_are_coherent_and_never_clipped() -> None:
    p = factored_probabilities(np.array([0.0, 0.01, 1.0]), np.array([0.3, 1.0, 0.5]))
    np.testing.assert_allclose(p.sum(axis=1), 1.0, atol=1e-15)
    np.testing.assert_allclose(p[1], [0.0, 0.99, 0.01])
    with pytest.raises(IncoherentProbabilityError):
        factored_probabilities(np.array([1.2]), np.array([0.5]))


def test_ramp_columns_are_non_decreasing_everywhere() -> None:
    x = np.linspace(-900, 900, 721)
    basis = _ramps(x, [-200.0, -50.0, 0.0, 75.0, 250.0])
    assert np.all(np.diff(basis, axis=0) >= 0)
    assert basis.shape[1] == 6  # left tail, 4 interior segments, right tail
    below = x < -200.0
    assert np.all(np.diff(basis[below, 0]) > 0)  # the left tail keeps its slope beyond k0


def test_fit_logistic_recovers_coefficients_and_respects_bounds() -> None:
    rng = np.random.default_rng(5)
    x = rng.normal(0, 1, (30_000, 2))
    y = rng.random(30_000) < 1 / (1 + np.exp(-(-1.0 + 0.8 * x[:, 0] - 0.5 * x[:, 1])))
    intercept, coef = fit_logistic(x, y, l2=1e-6)
    assert intercept == pytest.approx(-1.0, abs=0.06)
    np.testing.assert_allclose(coef, [0.8, -0.5], atol=0.06)
    # Bounding both coefficients at 0 from below forces the negative one to 0.
    _, bounded = fit_logistic(x, y, l2=1e-6, nonnegative=2)
    assert bounded[1] == 0.0
    assert bounded[0] > 0.5


def test_candidates_are_coherent(
    world: tuple[PanelBatch, PanelBatch, Preprocessor], fitted: dict[str, object]
) -> None:
    _, valid, _ = world
    for model in fitted.values():
        p = model.predict_proba(valid)  # type: ignore[attr-defined]
        assert p.shape == (valid.rows, 3)
        np.testing.assert_allclose(p.sum(axis=1), 1.0, atol=1e-12)


def test_candidates_ignore_absolute_rate_levels(
    world: tuple[PanelBatch, PanelBatch, Preprocessor], fitted: dict[str, object]
) -> None:
    """Moving the rate level and note rate together (fixed incentive) changes nothing."""
    _, valid, _ = world
    shifted = replace(
        valid,
        features={
            **valid.features,
            "market_rate_t1": np.asarray(valid.features["market_rate_t1"]) + 2.5,
            "note_rate_pct": np.asarray(valid.features["note_rate_pct"]) + 2.5,
            "pmms_application_based": np.ones(valid.rows),
        },
    )
    for name, model in fitted.items():
        np.testing.assert_array_equal(
            model.predict_proba(valid),  # type: ignore[attr-defined]
            model.predict_proba(shifted),  # type: ignore[attr-defined]
            err_msg=name,
        )
    for name in VARIANTS:
        assert not set(LEVEL_FEATURES) & set(fitted[name].feature_names())  # type: ignore[attr-defined]


def test_payoff_hazards_respect_their_monotone_constraints(
    world: tuple[PanelBatch, PanelBatch, Preprocessor], fitted: dict[str, object]
) -> None:
    _, valid, _ = world
    reference = valid.slice(0, 1500)
    incentive = tuple(float(v) for v in range(-600, 401, 50))
    burnout = tuple(float(v) for v in range(0, 121, 10))

    def payoff_only(model: object):  # type: ignore[no-untyped-def]
        class PayoffOnly:
            def predict_proba(self, batch: PanelBatch) -> np.ndarray:
                _, h = model.hazards(batch)  # type: ignore[attr-defined]
                return np.column_stack([1 - h, h, np.zeros_like(h)])

        return PayoffOnly()

    for name, model in fitted.items():
        h = payoff_only(model)
        assert ice_violation_share(h, reference, _set("incentive_bps"), incentive, direction=1) == 0
        if name != "X1_factored_gbm":
            assert (
                ice_violation_share(h, reference, _set("burnout_months"), burnout, direction=-1)
                == 0
            ), name


def test_h1_keeps_falling_below_the_training_incentive_range(
    world: tuple[PanelBatch, PanelBatch, Preprocessor], fitted: dict[str, object]
) -> None:
    _, valid, _ = world
    h1 = fitted["H1_constrained_hazard"]
    reference = valid.slice(0, 500)
    means = [
        float(h1.predict_proba(_set("incentive_bps")(reference, v))[:, 1].mean())  # type: ignore[attr-defined]
        for v in (-1200.0, -800.0, -400.0)
    ]
    assert means[0] < means[1] < means[2]  # trees would be flat out here
    slopes = h1.term_slopes()  # type: ignore[attr-defined]
    assert min(slopes["incentive_per_bp"]) >= 0
    assert max(slopes["burnout_per_month"]) <= 0


def test_x3_requires_derived_features(
    world: tuple[PanelBatch, PanelBatch, Preprocessor], fitted: dict[str, object]
) -> None:
    _, valid, _ = world
    stripped = replace(
        valid, features={k: v for k, v in valid.features.items() if k not in DERIVED_NUMERIC}
    )
    with pytest.raises(ValueError, match="derived features"):
        fitted["X3_factored_gbm"].predict_proba(stripped)  # type: ignore[attr-defined]
    fitted["X1_factored_gbm"].predict_proba(stripped)  # type: ignore[attr-defined]


def test_candidates_round_trip_through_the_registry(
    tmp_path: Path,
    world: tuple[PanelBatch, PanelBatch, Preprocessor],
    fitted: dict[str, object],
) -> None:
    _, valid, pre = world
    save_models(tmp_path, pre, fitted)  # type: ignore[arg-type]
    (tmp_path / "run-manifest.json").write_text(
        json.dumps({"models": list(fitted), "selection": {"selected": "X2_factored_gbm"}}),
        encoding="utf-8",
    )
    run = load_run(tmp_path)
    for name, model in fitted.items():
        np.testing.assert_array_equal(
            run.models[name].predict_proba(valid),
            model.predict_proba(valid),  # type: ignore[attr-defined]
            err_msg=name,
        )
    payload = json.loads((tmp_path / "models" / "H1_constrained_hazard.json").read_text())
    assert payload["monotone_term_slopes"]["incentive_per_bp"]
    assert not list(tmp_path.rglob("*.pkl"))
