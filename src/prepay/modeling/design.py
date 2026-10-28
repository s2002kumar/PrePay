"""Train-only preprocessing: imputation, standardization, one-hot levels and B-spline bases.

Everything is fitted on the training window only and serializes to plain JSON. Unseen or missing
categories map to explicit ``__other__`` / ``__missing__`` columns; they are never dropped.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from scipy.interpolate import BSpline

from prepay.arrays import FloatArray
from prepay.features.batch import PanelBatch
from prepay.features.spec import CATEGORICAL, NUMERIC

SPLINE_FEATURES = ("loan_age", "incentive_bps", "burnout_months")
SPLINE_DEGREE = 3
SPLINE_INTERIOR_KNOTS = 4
MIN_LEVEL_COUNT = 30
MISSING = "__missing__"
OTHER = "__other__"


def _as_text(values: np.ndarray) -> list[str]:
    return [MISSING if v is None else str(v) for v in values]


@dataclass(frozen=True, slots=True)
class Preprocessor:
    numeric: tuple[str, ...]
    categorical: tuple[str, ...]
    medians: dict[str, float]
    means: dict[str, float]
    scales: dict[str, float]
    levels: dict[str, list[str]]
    spline_knots: dict[str, list[float]]

    @classmethod
    def fit(cls, batch: PanelBatch, *, min_level_count: int = MIN_LEVEL_COUNT) -> Preprocessor:
        medians, means, scales = {}, {}, {}
        for name in NUMERIC:
            values = np.asarray(batch.features[name], dtype=np.float64)
            finite = values[np.isfinite(values)]
            median = float(np.median(finite)) if finite.size else 0.0
            filled = np.where(np.isfinite(values), values, median)
            medians[name] = median
            means[name] = float(filled.mean())
            std = float(filled.std())
            scales[name] = std if std > 1e-12 else 1.0
        levels = {}
        for name in CATEGORICAL:
            text, counts = np.unique(_as_text(batch.features[name]), return_counts=True)
            levels[name] = sorted(
                str(t)
                for t, c in zip(text, counts, strict=True)
                if c >= min_level_count and t != MISSING
            )
        knots = {}
        for name in SPLINE_FEATURES:
            values = np.asarray(batch.features[name], dtype=np.float64)
            values = values[np.isfinite(values)]
            interior = np.quantile(values, np.linspace(0, 1, SPLINE_INTERIOR_KNOTS + 2)[1:-1])
            low, high = float(values.min()), float(values.max())
            interior = np.unique(np.clip(interior, low, high))
            interior = interior[(interior > low) & (interior < high)]
            knots[name] = (
                [low] * (SPLINE_DEGREE + 1) + interior.tolist() + [high] * (SPLINE_DEGREE + 1)
            )
        return cls(NUMERIC, CATEGORICAL, medians, means, scales, levels, knots)

    # ----------------------------------------------------------------- shared pieces
    def _numeric_filled(self, batch: PanelBatch, name: str) -> FloatArray:
        values = np.asarray(batch.features[name], dtype=np.float64)
        return np.where(np.isfinite(values), values, self.medians[name])

    def _spline_basis(self, batch: PanelBatch, name: str) -> FloatArray:
        knots = np.asarray(self.spline_knots[name])
        x = np.clip(self._numeric_filled(batch, name), knots[0], knots[-1])
        basis = BSpline.design_matrix(x, knots, SPLINE_DEGREE).toarray()
        return np.asarray(basis, dtype=np.float64)

    def _one_hot(self, batch: PanelBatch, name: str) -> FloatArray:
        text = np.asarray(_as_text(batch.features[name]), dtype=object)
        known = self.levels[name]
        columns = [text == level for level in known]
        columns.append(text == MISSING)
        columns.append((text != MISSING) & ~np.isin(text, known))
        return np.column_stack(columns).astype(np.float64)

    # ----------------------------------------------------------------- dense (logistic)
    def dense(self, batch: PanelBatch) -> FloatArray:
        blocks = [
            np.column_stack(
                [
                    (self._numeric_filled(batch, n) - self.means[n]) / self.scales[n]
                    for n in self.numeric
                ]
            )
        ]
        blocks += [self._one_hot(batch, n) for n in self.categorical]
        blocks += [self._spline_basis(batch, n) for n in SPLINE_FEATURES]
        return np.hstack(blocks)

    def dense_names(self) -> list[str]:
        names = list(self.numeric)
        for n in self.categorical:
            names += [f"{n}={level}" for level in self.levels[n]] + [
                f"{n}={MISSING}",
                f"{n}={OTHER}",
            ]
        for n in SPLINE_FEATURES:
            names += [
                f"spline({n})[{i}]" for i in range(len(self.spline_knots[n]) - SPLINE_DEGREE - 1)
            ]
        return names

    # ----------------------------------------------------------------- trees (LightGBM)
    def tree_matrix(self, batch: PanelBatch) -> FloatArray:
        """Raw numerics (NaN kept for native missing handling) + categorical integer codes."""
        columns = [np.asarray(batch.features[n], dtype=np.float64) for n in self.numeric]
        for n in self.categorical:
            text = _as_text(batch.features[n])
            code = {level: float(i) for i, level in enumerate(self.levels[n])}
            columns.append(np.array([code.get(t, np.nan) for t in text]))
        return np.column_stack(columns)

    def tree_categorical_indices(self) -> list[int]:
        return list(range(len(self.numeric), len(self.numeric) + len(self.categorical)))

    def tree_names(self) -> list[str]:
        return [*self.numeric, *self.categorical]

    # ----------------------------------------------------------------- persistence
    def to_json(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["numeric"] = list(self.numeric)
        payload["categorical"] = list(self.categorical)
        return payload

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Preprocessor:
        return cls(
            numeric=tuple(payload["numeric"]),
            categorical=tuple(payload["categorical"]),
            medians={k: float(v) for k, v in payload["medians"].items()},
            means={k: float(v) for k, v in payload["means"].items()},
            scales={k: float(v) for k, v in payload["scales"].items()},
            levels={k: [str(x) for x in v] for k, v in payload["levels"].items()},
            spline_knots={k: [float(x) for x in v] for k, v in payload["spline_knots"].items()},
        )
