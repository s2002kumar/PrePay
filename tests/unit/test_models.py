"""Model coherence, serialization round trips, selection and calibration rules."""

from __future__ import annotations

import json

import numpy as np
import pytest

from prepay.features.panel import PanelBatch
from prepay.features.spec import CATEGORICAL, NUMERIC
from prepay.modeling.design import Preprocessor
from prepay.modeling.models import (
    GbmModel,
    IncoherentProbabilityError,
    LogisticModel,
    LookupBaseline,
    PsaBaseline,
    apply_temperature,
    check_simplex,
)
from prepay.modeling.train import calibration_decision, hash_fold, select

CODES = {
    "term_bucket": ["15y", "30y"],
    "loan_purpose": ["P", "C", "N", None],
    "occupancy_status": ["P", "I"],
    "channel": ["R", "C"],
    "first_time_homebuyer": ["Y", "N"],
    "property_type": ["SF", "CO"],
    "census_region": ["west", "south"],
    "month_of_year": list(range(1, 13)),
}


def make_batch(n: int, seed: int) -> PanelBatch:
    """Rows drawn from a known multinomial logit in incentive and age."""
    rng = np.random.default_rng(seed)
    features: dict[str, np.ndarray] = {name: rng.normal(0, 1, n) for name in NUMERIC}
    features["loan_age"] = rng.integers(1, 200, n).astype(float)
    features["incentive_bps"] = rng.normal(0, 120, n)
    features["burnout_months"] = rng.integers(0, 60, n).astype(float)
    features["note_rate_pct"] = rng.uniform(3, 7, n)
    features["remaining_payments"] = rng.integers(60, 360, n).astype(float)
    features["credit_score"] = np.where(rng.random(n) < 0.05, np.nan, rng.normal(740, 40, n))
    for name in CATEGORICAL:
        choices = CODES[name]
        features[name] = np.array(
            [choices[i] for i in rng.integers(0, len(choices), n)], dtype=object
        )
    prepay_logit = -4.5 + 0.012 * features["incentive_bps"] + 0.004 * features["loan_age"]
    credit_logit = np.full(n, -6.0)
    logits = np.column_stack([np.zeros(n), prepay_logit, credit_logit])
    p = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    y = np.array([rng.choice(3, p=row) for row in p])
    return PanelBatch(
        loan_id=np.array([f"L{i // 12:06d}" for i in range(n)], dtype=object),
        target_month=np.full(n, 2015 * 12),
        outcome_class=y,
        exposure_upb=rng.uniform(5e4, 5e5, n),
        features=features,
    )


@pytest.fixture(scope="module")
def batches() -> tuple[PanelBatch, PanelBatch]:
    return make_batch(20_000, 1), make_batch(8_000, 2)


def test_check_simplex_rejects_incoherent_rows() -> None:
    with pytest.raises(IncoherentProbabilityError, match="sum to 1"):
        check_simplex(np.array([[0.5, 0.4, 0.2]]))
    with pytest.raises(IncoherentProbabilityError, match="non-negative"):
        check_simplex(np.array([[1.1, -0.1, 0.0]]))
    with pytest.raises(IncoherentProbabilityError, match=r"\(n, 3\)"):
        check_simplex(np.array([[0.5, 0.5]]))


def test_every_model_is_coherent_and_round_trips(
    batches: tuple[PanelBatch, PanelBatch],
) -> None:
    train, valid = batches
    pre = Preprocessor.fit(train)
    pre_again = Preprocessor.from_json(json.loads(json.dumps(pre.to_json())))
    assert pre_again == pre
    models = [
        PsaBaseline.fit(train),
        LookupBaseline.fit(train),
        LogisticModel.fit(train, pre, c_regularization=1.0),
        GbmModel.fit(train, valid, pre, num_leaves=7, max_rounds=60),
    ]
    for model in models:
        p = model.predict_proba(valid)
        check_simplex(p)
        payload = json.loads(json.dumps(model.to_json()))
        assert payload["family"] == model.family
    gbm = models[3]
    assert isinstance(gbm, GbmModel)
    clone = GbmModel(pre_again, gbm.booster_text, gbm.params, gbm.best_iteration)
    np.testing.assert_array_equal(clone.predict_proba(valid), gbm.predict_proba(valid))


def test_numpy_logistic_inference_equals_sklearn(batches: tuple[PanelBatch, PanelBatch]) -> None:
    from sklearn.linear_model import LogisticRegression

    train, valid = batches
    pre = Preprocessor.fit(train)
    ours = LogisticModel.fit(train, pre, c_regularization=0.5)
    reference = LogisticRegression(C=0.5, max_iter=5000, tol=1e-7).fit(
        pre.dense(train), train.outcome_class
    )
    np.testing.assert_allclose(
        ours.predict_proba(valid), reference.predict_proba(pre.dense(valid)), atol=1e-12
    )


def test_logistic_learns_the_incentive_effect(batches: tuple[PanelBatch, PanelBatch]) -> None:
    train, valid = batches
    model = LogisticModel.fit(train, Preprocessor.fit(train), c_regularization=1.0)
    p = model.predict_proba(valid)
    high = valid.features["incentive_bps"] > 150
    low = valid.features["incentive_bps"] < -150
    assert p[high, 1].mean() > 3 * p[low, 1].mean()


def test_lookup_shrinks_sparse_cells_to_the_marginal(
    batches: tuple[PanelBatch, PanelBatch],
) -> None:
    train, _ = batches
    model = LookupBaseline.fit(train, prior_strength=1e9)
    table = np.asarray(model.table)
    np.testing.assert_allclose(table, np.tile(model.marginal, (table.shape[0], 1)), atol=1e-6)


def test_psa_baseline_uses_age_ramp(batches: tuple[PanelBatch, PanelBatch]) -> None:
    train, valid = batches
    p = PsaBaseline.fit(train).predict_proba(valid)
    young = valid.features["loan_age"] < 10
    seasoned = valid.features["loan_age"] > 40
    assert p[young, 1].max() < p[seasoned, 1].min()


def test_temperature_one_is_identity() -> None:
    p = np.array([[0.9, 0.08, 0.02], [0.5, 0.3, 0.2]])
    np.testing.assert_allclose(apply_temperature(p, 1.0), p, atol=1e-12)
    sharper = apply_temperature(p, 0.5)
    assert sharper[0, 0] > p[0, 0]


def test_calibration_adopted_only_when_cross_fit_improves(
    batches: tuple[PanelBatch, PanelBatch],
) -> None:
    train, valid = batches
    good = LogisticModel.fit(train, Preprocessor.fit(train), c_regularization=1.0)

    class Overconfident(LogisticModel):
        def predict_proba(self, batch: PanelBatch) -> np.ndarray:
            return apply_temperature(super().predict_proba(batch), 0.4)

    bad = Overconfident(good.preprocessor, good.coef, good.intercept, good.c_regularization)
    assert calibration_decision(bad, valid)["adopted"] is True
    assert 0.25 < calibration_decision(bad, valid)["temperature"] < 1.0 / 0.3


def test_selection_prefers_simplest_unless_significantly_worse(
    batches: tuple[PanelBatch, PanelBatch],
) -> None:
    _, valid = batches
    y = valid.outcome_class
    prevalence = np.bincount(y, minlength=3) / y.shape[0]
    flat = np.tile(prevalence, (y.shape[0], 1))
    perfect = np.full((y.shape[0], 3), 1e-6)
    perfect[np.arange(y.shape[0]), y] = 1 - 2e-6
    tied = select(valid, {"B1_lookup": flat, "B2_logistic": flat, "M1_lightgbm": flat})
    assert tied["selected"] == "B1_lookup"
    clear = select(valid, {"B1_lookup": flat, "B2_logistic": flat, "M1_lightgbm": perfect})
    assert clear["best"] == "M1_lightgbm"
    assert clear["selected"] == "M1_lightgbm"


def test_hash_fold_is_stable_and_balanced() -> None:
    folds = [hash_fold(f"F21Q1{i:07d}") for i in range(2000)]
    assert folds == [hash_fold(f"F21Q1{i:07d}") for i in range(2000)]
    assert 0.45 < sum(folds) / len(folds) < 0.55
