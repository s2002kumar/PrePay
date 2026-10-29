"""Applicability monitor (R1, ADR 0009 §7): is a forecast inside the conditions it was fitted on?

A :class:`SupportProfile` is fitted on a run's training rows. It holds:

- the 0.5-99.5% range of each monitored feature;
- training rows and payoffs per cell of three joint grids (incentive x rate level, incentive x
  age, incentive x six-month rate change);
- decile bins for the population stability index (PSI).

It classifies any feature rows:

- ``outside``: a monitored feature is beyond its training range;
- ``sparse``: otherwise, a joint cell had fewer than 1,000 training rows or 20 training payoffs;
- ``supported``: neither.

The weighted shares give a verdict of ``supported``, ``extrapolating`` or ``unsupported``.
**Population** batches (evaluation and monitoring windows) also use PSI. **Pool projections**
use row-level support only: a small pool always differs from the training population in mix,
and PSI would measure that rather than support (ADR 0009 amendment 1).

The verdict informs; it never changes a forecast (RELIABILITY_PLAN R3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from prepay.arrays import FloatArray, IntArray

MONITORED = ("incentive_bps", "market_rate_t1", "rate_change_6m_bps", "loan_age", "burnout_months")
PAIRS = (
    ("incentive_bps", "market_rate_t1"),
    ("incentive_bps", "loan_age"),
    ("incentive_bps", "rate_change_6m_bps"),
)
#: Fixed, documented cell edges (units of each feature); rows beyond the outer edges fall in the
#: outer cells, whose counts then decide sparsity.
EDGES: dict[str, tuple[float, ...]] = {
    "incentive_bps": (-300, -200, -150, -100, -50, -25, 0, 25, 50, 75, 100, 150, 200, 300),
    "market_rate_t1": (3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0),
    "loan_age": (6, 12, 24, 36, 60, 120, 180),
    "rate_change_6m_bps": (-150, -100, -50, -25, 0, 25, 50, 100, 150),
}
SUPPORT_QUANTILES = (0.005, 0.995)
MIN_CELL_ROWS = 1_000
MIN_CELL_PAYOFFS = 20
PSI_BINS = 10
PSI_FLOOR = 1e-4
PSI_REVIEW = 0.25
OUTSIDE_UNSUPPORTED = 0.25
OUTSIDE_EXTRAPOLATING = 0.05
OUTSIDE_OR_SPARSE_EXTRAPOLATING = 0.20

SUPPORTED, SPARSE, OUTSIDE = 0, 1, 2
Verdict = Literal["supported", "extrapolating", "unsupported"]
Features = Mapping[str, npt.NDArray[Any]]


def _values(features: Features, name: str) -> FloatArray:
    return np.asarray(features[name], dtype=np.float64)


def _cell_index(values: FloatArray, edges: tuple[float, ...]) -> IntArray:
    return np.asarray(np.searchsorted(np.asarray(edges), values, side="right"), dtype=np.int64)


@dataclass(frozen=True, slots=True)
class PsiBins:
    """Population stability index against training decile bins (``sum (o - e) ln(o / e)``)."""

    edges: list[float]  # interior edges (deciles of training)
    shares: list[float]  # training share per bin, len(edges) + 1

    def psi(self, values: FloatArray) -> float | None:
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            return None
        counts = np.bincount(
            np.searchsorted(np.asarray(self.edges), finite, side="right"),
            minlength=len(self.shares),
        )
        observed = np.maximum(counts / finite.size, PSI_FLOOR)
        expected = np.maximum(np.asarray(self.shares), PSI_FLOOR)
        return float(np.sum((observed - expected) * np.log(observed / expected)))

    @classmethod
    def fit(cls, values: FloatArray) -> PsiBins:
        finite = values[np.isfinite(values)]
        edges = np.unique(np.quantile(finite, np.linspace(0, 1, PSI_BINS + 1)[1:-1]))
        counts = np.bincount(np.searchsorted(edges, finite, side="right"), minlength=edges.size + 1)
        return cls(edges.tolist(), (counts / finite.size).tolist())


@dataclass(frozen=True, slots=True)
class SupportProfile:
    bounds: dict[str, list[float]]
    psi_bins: dict[str, PsiBins]
    cell_rows: dict[str, list[list[int]]]  # "a|b" -> counts[i_a][i_b]
    cell_payoffs: dict[str, list[list[int]]]
    training_rows: int

    @classmethod
    def fit(cls, features: Features, outcome_class: IntArray) -> SupportProfile:
        bounds, psi = {}, {}
        for name in MONITORED:
            values = _values(features, name)
            finite = values[np.isfinite(values)]
            bounds[name] = [float(np.quantile(finite, q)) for q in SUPPORT_QUANTILES]
            psi[name] = PsiBins.fit(values)
        rows, payoffs = {}, {}
        payoff = outcome_class == 1
        for a, b in PAIRS:
            ia, ib = (
                _cell_index(_values(features, a), EDGES[a]),
                _cell_index(_values(features, b), EDGES[b]),
            )
            shape = (len(EDGES[a]) + 1, len(EDGES[b]) + 1)
            count = np.zeros(shape, dtype=np.int64)
            hits = np.zeros(shape, dtype=np.int64)
            np.add.at(count, (ia, ib), 1)
            np.add.at(hits, (ia[payoff], ib[payoff]), 1)
            rows[f"{a}|{b}"] = count.tolist()
            payoffs[f"{a}|{b}"] = hits.tolist()
        return cls(bounds, psi, rows, payoffs, int(outcome_class.shape[0]))

    # ------------------------------------------------------------------ classification
    def outside(self, features: Features) -> dict[str, npt.NDArray[np.bool_]]:
        out = {}
        for name in MONITORED:
            values = _values(features, name)
            low, high = self.bounds[name]
            with np.errstate(invalid="ignore"):
                out[name] = np.isfinite(values) & ((values < low) | (values > high))
        return out

    def sparse(self, features: Features) -> npt.NDArray[np.bool_]:
        flags = np.zeros(_values(features, MONITORED[0]).shape[0], dtype=bool)
        for a, b in PAIRS:
            ia = _cell_index(_values(features, a), EDGES[a])
            ib = _cell_index(_values(features, b), EDGES[b])
            rows = np.asarray(self.cell_rows[f"{a}|{b}"])[ia, ib]
            hits = np.asarray(self.cell_payoffs[f"{a}|{b}"])[ia, ib]
            flags |= (rows < MIN_CELL_ROWS) | (hits < MIN_CELL_PAYOFFS)
        return flags

    def row_status(self, features: Features) -> IntArray:
        """0 supported, 1 sparse, 2 outside, per row."""
        outside = np.zeros(_values(features, MONITORED[0]).shape[0], dtype=bool)
        for flags in self.outside(features).values():
            outside |= flags
        status = np.where(outside, OUTSIDE, np.where(self.sparse(features), SPARSE, SUPPORTED))
        return np.asarray(status, dtype=np.int64)

    def assess(
        self,
        features: Features,
        weights: FloatArray | None = None,
        *,
        population: bool = True,
    ) -> dict[str, Any]:
        """Shares of outside and sparse rows, PSI (populations only) and the ADR 0009 verdict."""
        status = self.row_status(features)
        w = np.ones(status.shape[0]) if weights is None else np.asarray(weights, dtype=np.float64)
        total = float(w.sum())
        if total <= 0:
            return {"rows": int(status.shape[0]), "verdict": None, "note": "no weight"}
        outside_share = float(w[status == OUTSIDE].sum() / total)
        sparse_share = float(w[status == SPARSE].sum() / total)
        by_feature = {
            name: float(w[flags].sum() / total) for name, flags in self.outside(features).items()
        }
        psi = (
            {name: self.psi_bins[name].psi(_values(features, name)) for name in MONITORED}
            if population
            else {}
        )
        psi_flags = sorted(
            name for name, value in psi.items() if value is not None and value > PSI_REVIEW
        )
        reasons = [f"{name} outside training range" for name, s in by_feature.items() if s > 0]
        if psi_flags:
            reasons.append(f"PSI > {PSI_REVIEW} for {', '.join(psi_flags)}")
        verdict: Verdict
        if outside_share >= OUTSIDE_UNSUPPORTED:
            verdict = "unsupported"
        elif (
            outside_share >= OUTSIDE_EXTRAPOLATING
            or outside_share + sparse_share >= OUTSIDE_OR_SPARSE_EXTRAPOLATING
            or psi_flags
        ):
            verdict = "extrapolating"
        else:
            verdict = "supported"
        return {
            "rows": int(status.shape[0]),
            "weighting": "count" if weights is None else "balance",
            "outside_share": outside_share,
            "sparse_share": sparse_share,
            "outside_share_by_feature": by_feature,
            "psi": psi,
            "verdict": verdict,
            "reasons": reasons,
        }

    # ------------------------------------------------------------------ persistence
    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "prepay-support-profile",
            "bounds": self.bounds,
            "psi_bins": {
                k: {"edges": v.edges, "shares": v.shares} for k, v in self.psi_bins.items()
            },
            "cell_rows": self.cell_rows,
            "cell_payoffs": self.cell_payoffs,
            "training_rows": self.training_rows,
            "thresholds": {
                "support_quantiles": list(SUPPORT_QUANTILES),
                "min_cell_rows": MIN_CELL_ROWS,
                "min_cell_payoffs": MIN_CELL_PAYOFFS,
                "psi_review": PSI_REVIEW,
                "outside_unsupported": OUTSIDE_UNSUPPORTED,
                "outside_extrapolating": OUTSIDE_EXTRAPOLATING,
                "outside_or_sparse_extrapolating": OUTSIDE_OR_SPARSE_EXTRAPOLATING,
            },
            "edges": {k: list(v) for k, v in EDGES.items()},
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> SupportProfile:
        return cls(
            bounds={k: [float(x) for x in v] for k, v in payload["bounds"].items()},
            psi_bins={
                k: PsiBins([float(x) for x in v["edges"]], [float(x) for x in v["shares"]])
                for k, v in payload["psi_bins"].items()
            },
            cell_rows=payload["cell_rows"],
            cell_payoffs=payload["cell_payoffs"],
            training_rows=int(payload["training_rows"]),
        )
