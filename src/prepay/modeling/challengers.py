"""Reliability-program candidate families (RELIABILITY_PLAN §6, ADR 0008, ADR 0010).

Both families are factored competing-risk models. A credit hazard ``c(x)`` is fitted on every
row, and a payoff hazard ``h(x)`` on rows without a credit exit. They combine as::

    p_credit = c,   p_prepay = (1 - c) * h,   p_active = (1 - c) * (1 - h)

This is a valid simplex by construction, and nothing is clipped. It is the documented
challenger form of MODELING §6. A multiclass softmax can't carry a monotone payoff constraint
(ADR 0008), so these families are factored instead.

- :class:`FactoredGbm` (X1, X2, X3): two binary LightGBM boosters. The payoff booster never
  sees absolute rate levels (``market_rate_t1``, ``note_rate_pct``) or the PMMS method flag. It
  is non-decreasing in incentive; X2 and X3 are also non-increasing in burnout. X3 adds the
  derived behavioral features of :mod:`prepay.features.derived`, each non-decreasing.
- :class:`ConstrainedHazard` (H1): two L2-penalized logistic regressions fitted by bounded
  L-BFGS. The payoff logit is a sum of readable terms:
  - piecewise-linear incentive, non-decreasing, with logit-linear tails, so lock-in keeps
    deepening beyond the training range instead of going flat as trees do;
  - non-decreasing "new opportunity";
  - non-increasing burnout;
  - seasoning, the six-month rate change (held flat beyond its training range), seasonality
    and borrower terms.

  It has no rate level and no nominal loan size (both act as era proxies, RELIABILITY_PLAN §3).

Every artifact is JSON or LightGBM text, never pickle.
"""

from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

import numpy as np

from prepay.arrays import BoolArray, FloatArray
from prepay.evaluation.cohort import Predictor
from prepay.features.batch import PanelBatch
from prepay.features.derived import DERIVED_NUMERIC
from prepay.features.spec import NUMERIC
from prepay.modeling.design import Preprocessor
from prepay.modeling.models import GBM_BASE_PARAMS, HazardModel, check_simplex

#: Era-confounded or measurement-only inputs that no program candidate uses.
LEVEL_FEATURES = ("market_rate_t1", "note_rate_pct", "pmms_application_based")


def factored_probabilities(credit: FloatArray, payoff: FloatArray) -> FloatArray:
    """``(active, prepay, credit)`` from a credit hazard and a conditional payoff hazard."""
    c = np.asarray(credit, dtype=np.float64)
    h = np.asarray(payoff, dtype=np.float64)
    return check_simplex(np.column_stack([(1.0 - c) * (1.0 - h), (1.0 - c) * h, c]))


def _require_derived(batch: PanelBatch, needed: tuple[str, ...]) -> None:
    missing = [name for name in needed if name not in batch.features]
    if missing:
        raise ValueError(
            f"batch lacks derived features {missing}; add them with "
            "prepay.features.derived.augment(batch, rates)"
        )


# --------------------------------------------------------------------------- X1 / X2 / X3
@dataclass(frozen=True, slots=True)
class FactoredVariant:
    numeric: tuple[str, ...]
    payoff_monotone: dict[str, int]
    derived: tuple[str, ...] = ()


_BASE_NUMERIC = tuple(n for n in NUMERIC if n not in LEVEL_FEATURES)
VARIANTS: dict[str, FactoredVariant] = {
    "X1_factored_gbm": FactoredVariant(_BASE_NUMERIC, {"incentive_bps": 1}),
    "X2_factored_gbm": FactoredVariant(_BASE_NUMERIC, {"incentive_bps": 1, "burnout_months": -1}),
    "X3_factored_gbm": FactoredVariant(
        _BASE_NUMERIC + DERIVED_NUMERIC,
        {"incentive_bps": 1, "burnout_months": -1, **dict.fromkeys(DERIVED_NUMERIC, 1)},
        derived=DERIVED_NUMERIC,
    ),
}

BINARY_PARAMS: dict[str, Any] = {
    **{k: v for k, v in GBM_BASE_PARAMS.items() if k not in ("objective", "num_class", "metric")},
    "objective": "binary",
    "metric": "binary_logloss",
}


def _tree_matrix(pre: Preprocessor, batch: PanelBatch, numeric: tuple[str, ...]) -> FloatArray:
    """Raw numerics (NaN kept) followed by the run's categorical codes.

    Numerics come from :meth:`Preprocessor.tree_matrix` where the preprocessor knows them, so
    categorical coding is identical to M1's. Derived columns come straight from the batch.
    """
    full = pre.tree_matrix(batch)
    names = pre.tree_names()
    columns = [
        full[:, names.index(n)] if n in pre.numeric else np.asarray(batch.features[n], np.float64)
        for n in numeric
    ]
    columns += [full[:, names.index(n)] for n in pre.categorical]
    return np.column_stack(columns)


def _train_binary(
    x: FloatArray,
    y: BoolArray,
    x_valid: FloatArray,
    y_valid: BoolArray,
    params: dict[str, Any],
    names: list[str],
    categorical: list[int],
    *,
    max_rounds: int,
    early_stopping: int,
) -> tuple[str, int]:
    import lightgbm as lgb

    train_set = lgb.Dataset(
        x, label=y.astype(np.float64), feature_name=names, categorical_feature=categorical
    )
    valid_set = lgb.Dataset(x_valid, label=y_valid.astype(np.float64), reference=train_set)
    booster = lgb.train(
        params,
        train_set,
        num_boost_round=max_rounds,
        valid_sets=[valid_set],
        callbacks=[lgb.early_stopping(early_stopping, verbose=False)],
    )
    best = int(booster.best_iteration or booster.current_iteration())
    return booster.model_to_string(num_iteration=best), best


@dataclass
class FactoredGbm(HazardModel):
    preprocessor: Preprocessor
    variant: str
    credit_text: str
    payoff_text: str
    params: dict[str, Any]
    iterations: dict[str, int]
    family: ClassVar[str] = "X_factored_lightgbm"
    _boosters: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def name(self) -> str:
        return self.variant

    @property
    def spec(self) -> FactoredVariant:
        return VARIANTS[self.variant]

    def feature_names(self) -> list[str]:
        return [*self.spec.numeric, *self.preprocessor.categorical]

    @classmethod
    def fit(
        cls,
        train: PanelBatch,
        valid: PanelBatch,
        pre: Preprocessor,
        *,
        variant: str,
        num_leaves: int,
        max_rounds: int = 2000,
        early_stopping: int = 50,
        seed: int | None = None,
    ) -> FactoredGbm:
        spec = VARIANTS[variant]
        _require_derived(train, spec.derived)
        _require_derived(valid, spec.derived)
        names = [*spec.numeric, *pre.categorical]
        categorical = list(range(len(spec.numeric), len(names)))
        params = {**BINARY_PARAMS, "num_leaves": num_leaves}
        if seed is not None:
            params["seed"] = seed
        x, x_valid = _tree_matrix(pre, train, spec.numeric), _tree_matrix(pre, valid, spec.numeric)
        y, y_valid = train.outcome_class, valid.outcome_class
        credit_text, credit_best = _train_binary(
            x,
            y == 2,
            x_valid,
            y_valid == 2,
            params,
            names,
            categorical,
            max_rounds=max_rounds,
            early_stopping=early_stopping,
        )
        monotone = [spec.payoff_monotone.get(n, 0) for n in names]
        payoff_params = {**params, "monotone_constraints": monotone}
        keep, keep_valid = y != 2, y_valid != 2
        payoff_text, payoff_best = _train_binary(
            x[keep],
            y[keep] == 1,
            x_valid[keep_valid],
            y_valid[keep_valid] == 1,
            payoff_params,
            names,
            categorical,
            max_rounds=max_rounds,
            early_stopping=early_stopping,
        )
        return cls(
            pre,
            variant,
            credit_text,
            payoff_text,
            payoff_params,
            {"credit": credit_best, "payoff": payoff_best},
        )

    def _booster(self, part: str) -> Any:
        if part not in self._boosters:
            import lightgbm as lgb

            text = self.credit_text if part == "credit" else self.payoff_text
            self._boosters[part] = lgb.Booster(model_str=text)
        return self._boosters[part]

    def hazards(self, batch: PanelBatch) -> tuple[FloatArray, FloatArray]:
        """``(c, h)``: credit hazard and payoff hazard given no credit exit."""
        _require_derived(batch, self.spec.derived)
        x = _tree_matrix(self.preprocessor, batch, self.spec.numeric)
        credit = np.asarray(self._booster("credit").predict(x), dtype=np.float64)
        payoff = np.asarray(self._booster("payoff").predict(x), dtype=np.float64)
        return credit, payoff

    def _predict_block(self, batch: PanelBatch) -> FloatArray:
        return factored_probabilities(*self.hazards(batch))

    def to_json(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "variant": self.variant,
            "params": self.params,
            "iterations": self.iterations,
            "features": self.feature_names(),
            "payoff_monotone": self.spec.payoff_monotone,
        }


# --------------------------------------------------------------------------- H1
INCENTIVE_KNOT_QUANTILES = (0.01, 0.1, 0.25, 0.5, 0.75, 0.9, 0.99)
AGE_KNOTS = (6.0, 12.0, 24.0, 36.0, 60.0, 120.0)
RATE_CHANGE_KNOTS = (-50.0, 0.0, 50.0)
HAZARD_STATICS = (
    "credit_score",
    "credit_score_missing",
    "original_ltv",
    "ltv_missing",
    "original_dti",
    "dti_missing",
    "mi_pct",
    "number_of_units",
    "multiple_borrowers",
)
HAZARD_CATEGORICAL = (
    "term_bucket",
    "loan_purpose",
    "occupancy_status",
    "channel",
    "first_time_homebuyer",
    "property_type",
    "census_region",
)
H1_DERIVED = ("new_opportunity_bps",)


def _ramps(x: FloatArray, knots: list[float]) -> FloatArray:
    """Non-decreasing piecewise-linear basis with logit-linear tails.

    Columns: ``min(x - k0, 0)``, one ``clip(x - k_j, 0, k_{j+1} - k_j)`` per interior segment,
    and ``max(x - k_last, 0)``. Every column is non-decreasing in ``x``, so non-negative
    coefficients give a non-decreasing function, including beyond the outer knots.
    """
    columns = [np.minimum(x - knots[0], 0.0)]
    columns += [np.clip(x - lo, 0.0, hi - lo) for lo, hi in itertools.pairwise(knots)]
    columns.append(np.maximum(x - knots[-1], 0.0))
    return np.column_stack(columns)


def _positive_ramps(x: FloatArray, knots: list[float]) -> FloatArray:
    """Non-decreasing basis on the positive part only (0 at and below 0)."""
    edges = [0.0, *knots]
    columns = [np.clip(x - lo, 0.0, hi - lo) for lo, hi in itertools.pairwise(edges)]
    columns.append(np.maximum(x - edges[-1], 0.0))
    return np.column_stack(columns)


def _hinges(x: FloatArray, knots: tuple[float, ...] | list[float]) -> FloatArray:
    return np.column_stack([x, *(np.maximum(x - k, 0.0) for k in knots)])


def _positive_knots(values: FloatArray, quantiles: tuple[float, ...]) -> list[float]:
    positive = values[np.isfinite(values) & (values > 0)]
    if positive.size == 0:
        return [1.0]
    knots = np.unique(np.quantile(positive, quantiles))
    return [float(k) for k in knots if k > 0] or [1.0]


@dataclass(frozen=True, slots=True)
class HazardDesign:
    """Train-only transforms of H1. Serializes to JSON; every monotone column is non-decreasing."""

    incentive_knots: list[float]
    opportunity_knots: list[float]
    burnout_knots: list[float]
    rate_change_range: list[float]
    sato_range: list[float]
    medians: dict[str, float]
    payoff_center: list[float]
    payoff_scale: list[float]
    credit_center: list[float]
    credit_scale: list[float]

    # ------------------------------------------------------------------ raw blocks
    @staticmethod
    def _num(batch: PanelBatch, name: str) -> FloatArray:
        return np.asarray(batch.features[name], dtype=np.float64)

    def _filled(self, batch: PanelBatch, name: str) -> FloatArray:
        values = self._num(batch, name)
        return np.where(np.isfinite(values), values, self.medians[name])

    def _statics(self, batch: PanelBatch) -> FloatArray:
        return np.column_stack([self._filled(batch, n) for n in HAZARD_STATICS])

    @staticmethod
    def _one_hot(pre: Preprocessor, batch: PanelBatch) -> FloatArray:
        return np.hstack([pre.one_hot(batch, n) for n in HAZARD_CATEGORICAL])

    @staticmethod
    def _months(batch: PanelBatch) -> FloatArray:
        month = np.array(
            [0 if v is None else int(v) for v in batch.features["month_of_year"]], dtype=np.int64
        )
        return np.column_stack([(month == m).astype(np.float64) for m in range(2, 13)])

    def _age(self, batch: PanelBatch) -> FloatArray:
        return _hinges(np.clip(self._filled(batch, "loan_age"), 1.0, 480.0), AGE_KNOTS)

    def monotone_blocks(self, batch: PanelBatch) -> tuple[FloatArray, FloatArray, FloatArray]:
        """Incentive (non-decreasing), new opportunity (non-decreasing), -burnout ramps."""
        incentive = _ramps(self._filled(batch, "incentive_bps"), self.incentive_knots)
        opportunity = _positive_ramps(
            np.nan_to_num(self._num(batch, "new_opportunity_bps")), self.opportunity_knots
        )
        burnout = -_positive_ramps(self._filled(batch, "burnout_months"), self.burnout_knots)
        return incentive, opportunity, burnout

    def raw_payoff(self, pre: Preprocessor, batch: PanelBatch) -> tuple[FloatArray, int]:
        """Unscaled payoff columns and the count of leading monotone columns."""
        _require_derived(batch, H1_DERIVED)
        monotone = np.hstack(self.monotone_blocks(batch))
        low, high = self.rate_change_range
        rate_change = np.clip(self._filled(batch, "rate_change_6m_bps"), low, high)
        sato = np.clip(self._filled(batch, "sato_bps"), self.sato_range[0], self.sato_range[1])
        free = np.hstack(
            [
                _hinges(rate_change, RATE_CHANGE_KNOTS),
                sato[:, None],
                self._age(batch),
                self._months(batch),
                self._statics(batch),
                self._one_hot(pre, batch),
            ]
        )
        return np.hstack([monotone, free]), monotone.shape[1]

    def raw_credit(self, pre: Preprocessor, batch: PanelBatch) -> FloatArray:
        return np.hstack([self._age(batch), self._statics(batch), self._one_hot(pre, batch)])

    def payoff_matrix(self, pre: Preprocessor, batch: PanelBatch) -> tuple[FloatArray, int]:
        raw, n_monotone = self.raw_payoff(pre, batch)
        return (raw - np.asarray(self.payoff_center)) / np.asarray(self.payoff_scale), n_monotone

    def credit_matrix(self, pre: Preprocessor, batch: PanelBatch) -> FloatArray:
        raw = self.raw_credit(pre, batch)
        return np.asarray(
            (raw - np.asarray(self.credit_center)) / np.asarray(self.credit_scale),
            dtype=np.float64,
        )

    @classmethod
    def fit(cls, pre: Preprocessor, batch: PanelBatch) -> HazardDesign:
        def finite(name: str) -> FloatArray:
            values = cls._num(batch, name)
            return values[np.isfinite(values)]

        incentive = finite("incentive_bps")
        knots = np.unique(np.quantile(incentive, INCENTIVE_KNOT_QUANTILES))
        rate_change, sato = finite("rate_change_6m_bps"), finite("sato_bps")
        medians = {
            name: float(np.median(finite(name))) if finite(name).size else 0.0
            for name in (*HAZARD_STATICS, "incentive_bps", "burnout_months", "loan_age")
        }
        medians |= {"rate_change_6m_bps": 0.0, "sato_bps": float(np.median(sato))}
        draft = cls(
            incentive_knots=[float(k) for k in knots],
            opportunity_knots=_positive_knots(finite("new_opportunity_bps"), (0.5, 0.9)),
            burnout_knots=_positive_knots(finite("burnout_months"), (0.5, 0.9)),
            rate_change_range=[
                float(np.quantile(rate_change, 0.005)),
                float(np.quantile(rate_change, 0.995)),
            ],
            sato_range=[float(np.quantile(sato, 0.01)), float(np.quantile(sato, 0.99))],
            medians=medians,
            payoff_center=[],
            payoff_scale=[],
            credit_center=[],
            credit_scale=[],
        )
        payoff, n_monotone = draft.raw_payoff(pre, batch)
        credit = draft.raw_credit(pre, batch)

        def center_scale(raw: FloatArray, n_uncentered: int) -> tuple[list[float], list[float]]:
            # Monotone columns are only scaled: a positive scale keeps every slope's sign.
            center = raw.mean(axis=0)
            center[:n_uncentered] = 0.0
            scale = raw.std(axis=0)
            scale = np.where(scale > 1e-12, scale, 1.0)
            return center.tolist(), scale.tolist()

        payoff_center, payoff_scale = center_scale(payoff, n_monotone)
        credit_center, credit_scale = center_scale(credit, 0)
        return cls(
            **{
                **asdict(draft),
                "payoff_center": payoff_center,
                "payoff_scale": payoff_scale,
                "credit_center": credit_center,
                "credit_scale": credit_scale,
            }
        )


def _sigmoid(z: FloatArray) -> FloatArray:
    return np.asarray(np.exp(-np.logaddexp(0.0, -z)), dtype=np.float64)


def fit_logistic(
    x: FloatArray, y: BoolArray, *, l2: float, nonnegative: int = 0
) -> tuple[float, FloatArray]:
    """L2-penalized binary logistic regression by L-BFGS-B.

    Minimizes ``mean log loss + l2/2 * ||w||^2``; the intercept isn't penalized. The first
    ``nonnegative`` coefficients are bounded at 0 from below (the monotone terms).
    """
    from scipy.optimize import minimize

    n, k = x.shape
    target = y.astype(np.float64)
    base = float(np.clip(target.mean(), 1e-9, 1 - 1e-9))

    def objective(theta: FloatArray) -> tuple[float, FloatArray]:
        z = theta[0] + x @ theta[1:]
        loss = float(np.mean(np.logaddexp(0.0, z) - target * z)) + 0.5 * l2 * float(
            theta[1:] @ theta[1:]
        )
        residual = _sigmoid(z) - target
        grad = np.empty(k + 1)
        grad[0] = residual.mean()
        grad[1:] = x.T @ residual / n + l2 * theta[1:]
        return loss, grad

    start = np.zeros(k + 1)
    start[0] = np.log(base / (1 - base))
    bounds = [(None, None)] + [(0.0, None)] * nonnegative + [(None, None)] * (k - nonnegative)
    result = minimize(
        objective,
        start,
        jac=True,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": 5000, "ftol": 1e-13, "gtol": 1e-9},
    )
    if not result.success and "ABNORMAL" not in str(result.message):
        raise RuntimeError(f"logistic fit did not converge: {result.message}")
    theta = np.asarray(result.x, dtype=np.float64)
    return float(theta[0]), theta[1:]


@dataclass
class ConstrainedHazard(HazardModel):
    preprocessor: Preprocessor
    design: HazardDesign
    payoff_intercept: float
    payoff_coef: list[float]
    credit_intercept: float
    credit_coef: list[float]
    l2: float
    family: ClassVar[str] = "H1_constrained_hazard"

    @classmethod
    def fit(cls, train: PanelBatch, pre: Preprocessor, *, l2: float) -> ConstrainedHazard:
        design = HazardDesign.fit(pre, train)
        y = train.outcome_class
        credit_x = design.credit_matrix(pre, train)
        credit_b, credit_w = fit_logistic(credit_x, y == 2, l2=l2)
        del credit_x
        keep = y != 2
        payoff_x, n_monotone = design.payoff_matrix(pre, train)
        payoff_b, payoff_w = fit_logistic(
            payoff_x[keep], y[keep] == 1, l2=l2, nonnegative=n_monotone
        )
        return cls(pre, design, payoff_b, payoff_w.tolist(), credit_b, credit_w.tolist(), float(l2))

    def hazards(self, batch: PanelBatch) -> tuple[FloatArray, FloatArray]:
        payoff_x, _ = self.design.payoff_matrix(self.preprocessor, batch)
        credit_x = self.design.credit_matrix(self.preprocessor, batch)
        credit = _sigmoid(self.credit_intercept + credit_x @ np.asarray(self.credit_coef))
        payoff = _sigmoid(self.payoff_intercept + payoff_x @ np.asarray(self.payoff_coef))
        return credit, payoff

    def _predict_block(self, batch: PanelBatch) -> FloatArray:
        return factored_probabilities(*self.hazards(batch))

    def term_slopes(self) -> dict[str, list[float]]:
        """Per-segment logit slopes of the monotone terms (per bp or per month), for review."""
        coef = np.asarray(self.payoff_coef)
        scale = np.asarray(self.design.payoff_scale)
        effective = coef / scale
        n_inc = len(self.design.incentive_knots) + 1
        n_opp = len(self.design.opportunity_knots) + 1
        n_burn = len(self.design.burnout_knots) + 1
        return {
            "incentive_per_bp": effective[:n_inc].tolist(),
            "new_opportunity_per_bp": effective[n_inc : n_inc + n_opp].tolist(),
            "burnout_per_month": (-effective[n_inc + n_opp : n_inc + n_opp + n_burn]).tolist(),
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "design": asdict(self.design),
            "payoff_intercept": self.payoff_intercept,
            "payoff_coef": self.payoff_coef,
            "credit_intercept": self.credit_intercept,
            "credit_coef": self.credit_coef,
            "l2": self.l2,
            "monotone_term_slopes": self.term_slopes(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any], pre: Preprocessor) -> ConstrainedHazard:
        return cls(
            pre,
            HazardDesign(**payload["design"]),
            float(payload["payoff_intercept"]),
            [float(v) for v in payload["payoff_coef"]],
            float(payload["credit_intercept"]),
            [float(v) for v in payload["credit_coef"]],
            float(payload["l2"]),
        )


def ice_violation_share(
    model: Predictor,
    reference: PanelBatch,
    set_value: Any,
    grid: tuple[float, ...],
    *,
    direction: int,
) -> float:
    """Share of rows whose payoff probability moves against ``direction`` along ``grid``.

    ``set_value(batch, v)`` returns the batch with the probed input set to ``v`` (coherently).
    A tolerance of 1e-12 absorbs floating-point noise.
    """
    curves = np.column_stack([model.predict_proba(set_value(reference, v))[:, 1] for v in grid])
    steps = np.diff(curves, axis=1) * direction
    return float(np.mean(np.any(steps < -1e-12, axis=1))) if curves.size else 0.0
