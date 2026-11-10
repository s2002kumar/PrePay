"""Dependence-aware uncertainty and simultaneous inference for E01 (ADR 0014 §6).

One two-way (loan x month) pigeonhole bootstrap serves every statistic of a fold. Each replicate
draws a loan multiplicity and a month multiplicity, and weights each row by their product
(:func:`prepay.evaluation.inference.two_way`, Owen 2007). From those weights, in one pass over
the rows, it computes:

- every model's mean log loss, so the draw of any paired difference is a difference of draws;
- every model's payoff A/E, overall and in its bottom and top fifths by predicted payoff;
- every model's payoff A/E in each regime cell.

The random draws follow :func:`~prepay.evaluation.inference.two_way` exactly (same generator,
same order), so a paired difference here equals that function's draw for the same seed. A test
checks it.

Inference:
- **Unadjusted** intervals are 2.5-97.5% percentiles of the draws (descriptive).
- **Simultaneous** intervals for a declared family of ``m`` comparisons are Wald intervals,
  ``estimate ± z(1 - alpha / (2m)) x SE``, with SE the SD of the draws (Bonferroni). Percentile
  tails at that level would need far more replicates than the SE does.
- :func:`classify` turns a simultaneous interval into one of ``lower_loss``, ``higher_loss``,
  ``non_inferior`` and ``inconclusive``. An inconclusive comparison is not evidence of
  equivalence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from prepay.arrays import FloatArray, IntArray
from prepay.evaluation.inference import _codes, _counts

REPLICATES = 1000
SEED = 20261109
FAMILY_ALPHA = 0.05
CHUNK_ROWS = 1 << 18

Comparison = Literal["lower_loss", "higher_loss", "non_inferior", "inconclusive"]


@dataclass(frozen=True)
class CellGroups:
    """Row membership of the cells of one dimension: ``codes[i]`` in ``0..len(labels)-1``."""

    labels: tuple[str, ...]
    codes: IntArray


@dataclass(frozen=True)
class SuiteResult:
    """Point estimates (all rows weighted 1) and bootstrap draws, model order as given."""

    models: tuple[str, ...]
    replicates: int
    seed: int
    mean_log_loss: FloatArray  # (M,)
    mean_log_loss_draws: FloatArray  # (R, M)
    payoff_ae: FloatArray  # (M,)
    payoff_ae_draws: FloatArray  # (R, M)
    fifth_ae: dict[str, FloatArray]  # "bottom"/"top" -> (M,)
    fifth_ae_draws: dict[str, FloatArray]  # "bottom"/"top" -> (R, M)
    cell_ae: dict[str, FloatArray]  # dimension -> (K, M)
    cell_ae_draws: dict[str, FloatArray]  # dimension -> (R, K, M)


def fifth_masks(payoff_prob: FloatArray) -> dict[str, np.ndarray]:
    """Per model, the bottom and top fifth of rows by predicted payoff, ``(N, M)`` booleans.

    Same construction as :func:`prepay.evaluation.forward.quintile_ae`: a stable sort, split
    into five near-equal parts.
    """
    n, m = payoff_prob.shape
    out = {"bottom": np.zeros((n, m), dtype=bool), "top": np.zeros((n, m), dtype=bool)}
    for j in range(m):
        parts = np.array_split(np.argsort(payoff_prob[:, j], kind="stable"), 5)
        out["bottom"][parts[0], j] = True
        out["top"][parts[-1], j] = True
    return out


class _Sums:
    """Weighted sums for one replicate (or the unweighted estimate), accumulated by chunk."""

    def __init__(self, m: int, cells: Mapping[str, CellGroups]) -> None:
        self.weight = 0.0
        self.log_loss = np.zeros(m)
        self.observed = 0.0
        self.expected = np.zeros(m)
        self.fifth_observed = {k: np.zeros(m) for k in ("bottom", "top")}
        self.fifth_expected = {k: np.zeros(m) for k in ("bottom", "top")}
        self.cell_observed = {d: np.zeros(len(g.labels)) for d, g in cells.items()}
        self.cell_expected = {d: np.zeros((len(g.labels), m)) for d, g in cells.items()}

    def add(
        self,
        w: FloatArray,
        log_loss: FloatArray,
        payoff_prob: FloatArray,
        observed: FloatArray,
        fifths: Mapping[str, np.ndarray],
        cells: Mapping[str, IntArray],
    ) -> None:
        wy = w * observed
        wp = w[:, None] * payoff_prob
        self.weight += float(w.sum())
        self.log_loss += w @ log_loss
        self.observed += float(wy.sum())
        self.expected += wp.sum(axis=0)
        for key, mask in fifths.items():
            self.fifth_observed[key] += wy @ mask
            self.fifth_expected[key] += np.where(mask, wp, 0.0).sum(axis=0)
        for dim, codes in cells.items():
            k = self.cell_observed[dim].shape[0]
            self.cell_observed[dim] += np.bincount(codes, weights=wy, minlength=k)[:k]
            for j in range(wp.shape[1]):
                self.cell_expected[dim][:, j] += np.bincount(codes, weights=wp[:, j], minlength=k)[
                    :k
                ]

    def ratios(self) -> dict[str, Any]:
        with np.errstate(divide="ignore", invalid="ignore"):
            return {
                "mean_log_loss": self.log_loss / self.weight,
                "payoff_ae": self.observed / self.expected,
                "fifth_ae": {
                    k: self.fifth_observed[k] / self.fifth_expected[k] for k in self.fifth_observed
                },
                "cell_ae": {
                    d: self.cell_observed[d][:, None] / self.cell_expected[d]
                    for d in self.cell_observed
                },
            }


def two_way_suite(
    loans: np.ndarray,
    months: np.ndarray,
    models: tuple[str, ...],
    log_loss: FloatArray,
    payoff_prob: FloatArray,
    observed_payoff: FloatArray,
    cells: Mapping[str, CellGroups],
    *,
    replicates: int = REPLICATES,
    seed: int = SEED,
    chunk_rows: int = CHUNK_ROWS,
) -> SuiteResult:
    """Every E01 bootstrap statistic of one fold from one set of two-way replicates.

    ``log_loss`` and ``payoff_prob`` are ``(N, M)``, one column per model in ``models``.
    Cell rows with code ``-1`` belong to no cell of that dimension. Memory beyond the inputs is
    one chunk of ``chunk_rows`` rows times the number of models.
    """
    n, m = log_loss.shape
    if payoff_prob.shape != (n, m) or observed_payoff.shape != (n,) or len(models) != m:
        raise ValueError("inputs must be (N, M) per model and (N,) observed")
    loan_codes, n_loans = _codes(loans)
    month_codes, n_months = _codes(months)
    fifths = fifth_masks(payoff_prob)
    # Rows outside every cell of a dimension go to a spare last bin, dropped by ``[:k]``.
    cell_codes = {
        d: np.where(g.codes < 0, len(g.labels), g.codes).astype(np.int64) for d, g in cells.items()
    }
    chunks = [(s, min(s + chunk_rows, n)) for s in range(0, n, chunk_rows)]

    def accumulate(weights: FloatArray | None) -> dict[str, Any]:
        sums = _Sums(m, cells)
        for a, b in chunks:
            w = np.ones(b - a) if weights is None else weights[a:b]
            sums.add(
                w,
                log_loss[a:b],
                payoff_prob[a:b],
                observed_payoff[a:b],
                {k: v[a:b] for k, v in fifths.items()},
                {d: c[a:b] for d, c in cell_codes.items()},
            )
        return sums.ratios()

    estimate = accumulate(None)
    rng = np.random.Generator(np.random.PCG64(seed))
    draws: list[dict[str, Any]] = []
    for _ in range(replicates):
        # Same draws, in the same order, as prepay.evaluation.inference.two_way.
        weight = _counts(rng, n_loans)[loan_codes] * _counts(rng, n_months)[month_codes]
        draws.append(accumulate(weight))
    return SuiteResult(
        models=models,
        replicates=replicates,
        seed=seed,
        mean_log_loss=estimate["mean_log_loss"],
        mean_log_loss_draws=np.array([d["mean_log_loss"] for d in draws]),
        payoff_ae=estimate["payoff_ae"],
        payoff_ae_draws=np.array([d["payoff_ae"] for d in draws]),
        fifth_ae=estimate["fifth_ae"],
        fifth_ae_draws={k: np.array([d["fifth_ae"][k] for d in draws]) for k in fifths},
        cell_ae=estimate["cell_ae"],
        cell_ae_draws={dim: np.array([d["cell_ae"][dim] for d in draws]) for dim in cells},
    )


# --------------------------------------------------------------------------- summaries
def _percentiles(draws: FloatArray) -> tuple[float | None, float | None]:
    finite = draws[np.isfinite(draws)]
    if finite.size < 2:
        return None, None
    return float(np.quantile(finite, 0.025)), float(np.quantile(finite, 0.975))


def _sd(draws: FloatArray) -> float | None:
    finite = draws[np.isfinite(draws)]
    return float(np.std(finite, ddof=1)) if finite.size >= 2 else None


def paired(suite: SuiteResult, candidate: str, reference: str) -> dict[str, Any]:
    """Paired mean log-loss difference (candidate - reference): effect sizes and uncertainty."""
    i, j = suite.models.index(candidate), suite.models.index(reference)
    estimate = float(suite.mean_log_loss[i] - suite.mean_log_loss[j])
    draws = suite.mean_log_loss_draws[:, i] - suite.mean_log_loss_draws[:, j]
    low, high = _percentiles(draws)
    reference_loss = float(suite.mean_log_loss[j])
    return {
        "candidate": candidate,
        "reference": reference,
        "estimate": estimate,
        "relative_to_reference": estimate / reference_loss if reference_loss > 0 else None,
        "reference_log_loss": reference_loss,
        "se": _sd(draws),
        "unadjusted_low": low,
        "unadjusted_high": high,
        "unadjusted_kind": f"two_way_percentile_95_{suite.replicates}",
    }


def ratio(estimate: float, draws: FloatArray) -> dict[str, Any]:
    """A ratio statistic (A/E) with its unadjusted two-way percentile interval."""
    low, high = _percentiles(draws)
    value = float(estimate)
    return {
        "estimate": value if np.isfinite(value) else None,
        "low": low,
        "high": high,
        "kind": "two_way_percentile_95",
    }


def month_block_mean(
    values: FloatArray, *, replicates: int = REPLICATES, seed: int = SEED
) -> dict[str, Any]:
    """Mean of a monthly series (one value per month) with a month-block bootstrap interval."""
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0:
        return {"estimate": None, "low": None, "high": None, "kind": "month_block_percentile_95"}
    rng = np.random.Generator(np.random.PCG64(seed))
    means = np.array(
        [values[rng.integers(0, values.size, values.size)].mean() for _ in range(replicates)]
    )
    low, high = _percentiles(means)
    return {
        "estimate": float(values.mean()),
        "low": low,
        "high": high,
        "kind": "month_block_percentile_95",
    }


def bonferroni_z(family_size: int, alpha: float = FAMILY_ALPHA) -> float:
    """Two-sided normal quantile for a familywise ``alpha`` over ``family_size`` comparisons."""
    from scipy.stats import norm

    if family_size < 1:
        raise ValueError("a family needs at least one comparison")
    return float(norm.ppf(1.0 - alpha / (2.0 * family_size)))


def simultaneous(estimate: float, se: float | None, z: float) -> tuple[float | None, float | None]:
    if se is None or not np.isfinite(se):
        return None, None
    return estimate - z * se, estimate + z * se


def classify(low: float | None, high: float | None, margin: float) -> Comparison:
    """Class of a candidate-minus-reference loss difference from its simultaneous interval.

    ``lower_loss`` if the whole interval is below 0, ``higher_loss`` if above 0, ``non_inferior``
    if it lies below ``margin`` without showing lower loss, otherwise ``inconclusive``.
    """
    if low is None or high is None:
        return "inconclusive"
    if high < 0.0:
        return "lower_loss"
    if low > 0.0:
        return "higher_loss"
    if high < margin:
        return "non_inferior"
    return "inconclusive"
