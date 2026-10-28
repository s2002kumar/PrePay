"""Competing-risk hazard models with coherent three-class output (MODELING §6).

Every model returns an ``(n, 3)`` array of month-t probabilities in class order
``(active, prepay, credit)``, matching ``outcome_class`` 0/1/2, and :func:`check_simplex` rejects
any row that is not a valid simplex. Models serialize to JSON (LightGBM to its native text
format) and never to pickle, so loading an artifact cannot execute code.

- **B0** PSA prepayment benchmark plus a constant train-period credit rate (reference only).
- **B1** pooled empirical lookup by loan age x incentive, smoothed toward the marginal.
- **B2** L2-regularized multinomial logistic regression with spline terms.
- **M1** LightGBM joint multiclass softmax (not two clipped binary models).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np

from prepay.arrays import FloatArray, IntArray
from prepay.features.batch import PanelBatch
from prepay.finance.rates import psa_smm
from prepay.modeling.design import Preprocessor

CLASSES = ("active", "prepay", "credit")
SIMPLEX_ATOL = 1e-9


class IncoherentProbabilityError(ValueError):
    """A model produced probabilities that are not a valid simplex."""


def check_simplex(p: FloatArray) -> FloatArray:
    if p.ndim != 2 or p.shape[1] != len(CLASSES):
        raise IncoherentProbabilityError(f"expected (n, 3) probabilities, got {p.shape}")
    if not np.all(np.isfinite(p)) or np.any(p < 0.0):
        raise IncoherentProbabilityError("probabilities must be finite and non-negative")
    deviation = float(np.max(np.abs(p.sum(axis=1) - 1.0))) if p.size else 0.0
    if deviation > SIMPLEX_ATOL:
        raise IncoherentProbabilityError(f"rows do not sum to 1 (max deviation {deviation:.3g})")
    return p


def softmax(z: FloatArray) -> FloatArray:
    shifted = z - z.max(axis=1, keepdims=True)
    e = np.exp(shifted)
    return np.asarray(e / e.sum(axis=1, keepdims=True), dtype=np.float64)


class HazardModel(ABC):
    family: ClassVar[str]

    @abstractmethod
    def predict_proba(self, batch: PanelBatch) -> FloatArray: ...

    @abstractmethod
    def to_json(self) -> dict[str, Any]: ...

    @property
    def name(self) -> str:
        return self.family


# --------------------------------------------------------------------------- B0
@dataclass
class PsaBaseline(HazardModel):
    """100% PSA voluntary-payoff SMM by loan age; credit hazard = train mean monthly rate."""

    credit_rate: float
    speed: float = 1.0
    family: ClassVar[str] = "B0_psa"

    @classmethod
    def fit(cls, batch: PanelBatch) -> PsaBaseline:
        return cls(credit_rate=float(np.mean(batch.outcome_class == 2)))

    def predict_proba(self, batch: PanelBatch) -> FloatArray:
        age = np.maximum(np.asarray(batch.features["loan_age"], dtype=np.float64), 0.0)
        prepay = psa_smm(age, self.speed)
        credit = np.full(prepay.shape, self.credit_rate)
        return check_simplex(np.column_stack([1.0 - prepay - credit, prepay, credit]))

    def to_json(self) -> dict[str, Any]:
        return {"family": self.family, "credit_rate": self.credit_rate, "speed": self.speed}


# --------------------------------------------------------------------------- B1
AGE_EDGES = (0.0, 6.0, 12.0, 24.0, 36.0, 60.0, 120.0)
INCENTIVE_EDGES = (-100.0, 0.0, 50.0, 100.0, 150.0, 200.0)


@dataclass
class LookupBaseline(HazardModel):
    """Empirical class frequencies per (age bin, incentive bin) cell with Dirichlet smoothing.

    ``p(cell) = (counts + k * marginal) / (n_cell + k)``: sparse cells shrink to the marginal.
    """

    table: list[list[float]]
    marginal: list[float]
    prior_strength: float
    age_edges: tuple[float, ...] = AGE_EDGES
    incentive_edges: tuple[float, ...] = INCENTIVE_EDGES
    family: ClassVar[str] = "B1_lookup"

    def _cells(self, batch: PanelBatch) -> IntArray:
        age = np.asarray(batch.features["loan_age"], dtype=np.float64)
        incentive = np.nan_to_num(np.asarray(batch.features["incentive_bps"], dtype=np.float64))
        age_bin = np.searchsorted(self.age_edges, age, side="left")
        incentive_bin = np.searchsorted(self.incentive_edges, incentive, side="right")
        return np.asarray(age_bin * (len(self.incentive_edges) + 1) + incentive_bin, dtype=np.int64)

    @classmethod
    def fit(cls, batch: PanelBatch, *, prior_strength: float = 200.0) -> LookupBaseline:
        empty = cls(table=[], marginal=[], prior_strength=prior_strength)
        cells = empty._cells(batch)
        n_cells = (len(AGE_EDGES) + 1) * (len(INCENTIVE_EDGES) + 1)
        counts = np.zeros((n_cells, 3))
        np.add.at(counts, (cells, batch.outcome_class), 1.0)
        marginal = counts.sum(axis=0) / counts.sum()
        smoothed = (counts + prior_strength * marginal) / (
            counts.sum(axis=1, keepdims=True) + prior_strength
        )
        return cls(
            table=smoothed.tolist(), marginal=marginal.tolist(), prior_strength=prior_strength
        )

    def predict_proba(self, batch: PanelBatch) -> FloatArray:
        return check_simplex(np.asarray(self.table)[self._cells(batch)])

    def to_json(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "table": self.table,
            "marginal": self.marginal,
            "prior_strength": self.prior_strength,
            "age_edges": list(self.age_edges),
            "incentive_edges": list(self.incentive_edges),
        }


# --------------------------------------------------------------------------- B2
@dataclass
class LogisticModel(HazardModel):
    """Multinomial logistic regression; inference is plain NumPy from stored coefficients."""

    preprocessor: Preprocessor
    coef: list[list[float]]
    intercept: list[float]
    c_regularization: float
    family: ClassVar[str] = "B2_logistic"

    @classmethod
    def fit(cls, batch: PanelBatch, pre: Preprocessor, *, c_regularization: float) -> LogisticModel:
        from sklearn.linear_model import LogisticRegression

        if set(np.unique(batch.outcome_class)) != {0, 1, 2}:
            raise ValueError("training data must contain all three outcome classes")
        model = LogisticRegression(C=c_regularization, max_iter=5000, tol=1e-7)
        model.fit(pre.dense(batch), batch.outcome_class)
        return cls(pre, model.coef_.tolist(), model.intercept_.tolist(), c_regularization)

    def predict_proba(self, batch: PanelBatch) -> FloatArray:
        z = self.preprocessor.dense(batch) @ np.asarray(self.coef).T + np.asarray(self.intercept)
        return check_simplex(softmax(z))

    def to_json(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "coef": self.coef,
            "intercept": self.intercept,
            "c_regularization": self.c_regularization,
            "feature_names": self.preprocessor.dense_names(),
        }


# --------------------------------------------------------------------------- M1
GBM_BASE_PARAMS: dict[str, Any] = {
    "objective": "multiclass",
    "num_class": 3,
    "metric": "multi_logloss",
    "learning_rate": 0.05,
    "min_data_in_leaf": 200,
    "feature_fraction": 0.9,
    "lambda_l2": 1.0,
    "max_bin": 255,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": 4,
    "seed": 20261028,
    "verbosity": -1,
}


@dataclass
class GbmModel(HazardModel):
    preprocessor: Preprocessor
    booster_text: str
    params: dict[str, Any]
    best_iteration: int
    family: ClassVar[str] = "M1_lightgbm"
    _booster: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def fit(
        cls,
        train: PanelBatch,
        valid: PanelBatch,
        pre: Preprocessor,
        *,
        num_leaves: int,
        max_rounds: int = 2000,
        early_stopping: int = 50,
    ) -> GbmModel:
        import lightgbm as lgb

        params = {**GBM_BASE_PARAMS, "num_leaves": num_leaves}
        categorical = pre.tree_categorical_indices()
        train_set = lgb.Dataset(
            pre.tree_matrix(train),
            label=train.outcome_class,
            feature_name=pre.tree_names(),
            categorical_feature=categorical,
            free_raw_data=False,
        )
        valid_set = lgb.Dataset(
            pre.tree_matrix(valid),
            label=valid.outcome_class,
            reference=train_set,
            free_raw_data=False,
        )
        booster = lgb.train(
            params,
            train_set,
            num_boost_round=max_rounds,
            valid_sets=[valid_set],
            callbacks=[lgb.early_stopping(early_stopping, verbose=False)],
        )
        best = int(booster.best_iteration or booster.current_iteration())
        text = booster.model_to_string(num_iteration=best)
        return cls(pre, text, params, best)

    def _model(self) -> Any:
        if self._booster is None:
            import lightgbm as lgb

            self._booster = lgb.Booster(model_str=self.booster_text)
        return self._booster

    def predict_proba(self, batch: PanelBatch) -> FloatArray:
        raw = self._model().predict(self.preprocessor.tree_matrix(batch))
        return check_simplex(np.asarray(raw, dtype=np.float64))

    def feature_importance(self) -> dict[str, float]:
        gains = self._model().feature_importance(importance_type="gain")
        return {n: float(g) for n, g in zip(self.preprocessor.tree_names(), gains, strict=True)}

    def to_json(self) -> dict[str, Any]:
        return {"family": self.family, "params": self.params, "best_iteration": self.best_iteration}


# --------------------------------------------------------------------------- calibration
@dataclass
class TemperatureCalibrated(HazardModel):
    """Multiclass temperature scaling: ``softmax(log p / T)`` fitted on Validation B."""

    base: HazardModel
    temperature: float

    @property
    def name(self) -> str:
        return f"{self.base.name}+temperature"

    family: ClassVar[str] = "temperature"

    def predict_proba(self, batch: PanelBatch) -> FloatArray:
        return check_simplex(apply_temperature(self.base.predict_proba(batch), self.temperature))

    def to_json(self) -> dict[str, Any]:
        return {"family": self.family, "base": self.base.name, "temperature": self.temperature}


def apply_temperature(p: FloatArray, temperature: float) -> FloatArray:
    return softmax(np.log(np.clip(p, 1e-300, 1.0)) / temperature)
