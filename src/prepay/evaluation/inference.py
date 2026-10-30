"""Bootstrap intervals for loan-month panels with shared monthly shocks (ADR 0010 amendment 2).

Rows of a hazard panel are dependent in two ways:

- **within a loan**, the same borrower over many months;
- **within a month**, every loan sees the same rates, seasonality and economic news.

A loan-cluster bootstrap captures the first and ignores the second. Its intervals describe
uncertainty *for these particular months*. They don't describe "months like these", which is
what a forward claim generalizes to.

- :func:`loan_cluster` resamples loans.
- :func:`month_block` resamples calendar months.
- :func:`two_way` is the pigeonhole bootstrap (Owen 2007). It resamples loans and months
  independently, and weights each row by its loan multiplicity times its month multiplicity. That
  carries both sources of variation, and is conservative when one of them is absent.

:func:`coverage_study` measures how often each 95% interval covers a known mean, in simulated
panels with loan effects, month effects and noise. It is the evidence behind using two-way
intervals for forward decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from prepay.arrays import FloatArray, IntArray


def _codes(keys: np.ndarray) -> tuple[IntArray, int]:
    _, codes = np.unique(keys, return_inverse=True)
    codes = np.asarray(codes, dtype=np.int64).reshape(-1)
    return codes, int(codes.max(initial=-1)) + 1


def _counts(rng: np.random.Generator, n: int) -> FloatArray:
    """Multiplicity of each of ``n`` units in one resample of ``n`` with replacement."""
    return np.bincount(rng.integers(0, n, size=n), minlength=n).astype(np.float64)


def loan_cluster(
    loans: np.ndarray, values: FloatArray, *, replicates: int, seed: int
) -> FloatArray:
    """Replicate means resampling loans only."""
    codes, n = _codes(loans)
    sums = np.bincount(codes, weights=values, minlength=n)
    sizes = np.bincount(codes, minlength=n).astype(np.float64)
    rng = np.random.Generator(np.random.PCG64(seed))
    out = np.empty(replicates)
    for b in range(replicates):
        w = _counts(rng, n)
        out[b] = (w @ sums) / (w @ sizes)
    return out


def month_block(
    months: np.ndarray, values: FloatArray, *, replicates: int, seed: int
) -> FloatArray:
    """Replicate means resampling whole calendar months."""
    return loan_cluster(months, values, replicates=replicates, seed=seed)


def two_way(
    loans: np.ndarray,
    months: np.ndarray,
    values: FloatArray,
    *,
    replicates: int,
    seed: int,
) -> FloatArray:
    """Pigeonhole bootstrap: row weight = loan multiplicity x month multiplicity."""
    loan_codes, n_loans = _codes(loans)
    month_codes, n_months = _codes(months)
    rng = np.random.Generator(np.random.PCG64(seed))
    out = np.empty(replicates)
    for b in range(replicates):
        weight = _counts(rng, n_loans)[loan_codes] * _counts(rng, n_months)[month_codes]
        total = weight.sum()
        out[b] = (weight @ values) / total if total > 0 else np.nan
    return out


@dataclass(frozen=True, slots=True)
class PairedInterval:
    estimate: float
    low: float
    high: float
    p_one_sided: float  # evidence that the mean is below 0 (candidate better)
    method: str

    def as_dict(self) -> dict[str, float | str]:
        return {
            "estimate": self.estimate,
            "low": self.low,
            "high": self.high,
            "p_one_sided": self.p_one_sided,
            "method": self.method,
        }


def summarize(draws: FloatArray, estimate: float, method: str) -> PairedInterval:
    finite = draws[np.isfinite(draws)]
    return PairedInterval(
        estimate=float(estimate),
        low=float(np.quantile(finite, 0.025)),
        high=float(np.quantile(finite, 0.975)),
        p_one_sided=float((1 + np.sum(finite >= 0.0)) / (finite.size + 1)),
        method=method,
    )


# --------------------------------------------------------------------------- coverage study
def simulate_panel(
    rng: np.random.Generator,
    *,
    loans: int,
    months: int,
    sd_loan: float,
    sd_month: float,
    sd_noise: float,
    mean: float = 0.0,
) -> tuple[IntArray, IntArray, FloatArray]:
    """Unbalanced loan-month panel of paired differences with loan and month effects.

    Each loan is observed for a random run of consecutive months, as loans enter and leave a
    real panel. ``value = mean + loan effect + month effect + noise``, with heavy-tailed noise
    (Student t, 4 degrees of freedom) like log-loss differences of rare events.
    """
    start = rng.integers(0, months, size=loans)
    length = rng.integers(1, months + 1, size=loans)
    end = np.minimum(start + length, months)
    loan_idx = np.repeat(np.arange(loans), end - start)
    month_idx = np.concatenate([np.arange(s, e) for s, e in zip(start, end, strict=True)])
    loan_effect = rng.normal(0.0, sd_loan, loans)
    month_effect = rng.normal(0.0, sd_month, months)
    noise = rng.standard_t(4, size=loan_idx.shape[0]) * sd_noise / np.sqrt(2.0)
    values = mean + loan_effect[loan_idx] + month_effect[month_idx] + noise
    return loan_idx.astype(np.int64), month_idx.astype(np.int64), values


def coverage_study(
    *,
    loans: int = 2000,
    months: int = 12,
    sd_loan: float = 1.0,
    sd_month: float = 0.0,
    sd_noise: float = 1.0,
    simulations: int = 200,
    replicates: int = 200,
    seed: int = 20261030,
) -> dict[str, Any]:
    """Share of simulated panels whose 95% interval covers the true mean, per method.

    The true mean is the data-generating ``mean`` (0): it treats months as a draw from a
    population of months, which is what a forward claim generalizes to.
    """
    rng = np.random.Generator(np.random.PCG64(seed))
    hits = {"loan_cluster": 0, "month_block": 0, "two_way": 0}
    widths: dict[str, list[float]] = {k: [] for k in hits}
    for s in range(simulations):
        loan_idx, month_idx, values = simulate_panel(
            rng, loans=loans, months=months, sd_loan=sd_loan, sd_month=sd_month, sd_noise=sd_noise
        )
        estimate = float(values.mean())
        draws = {
            "loan_cluster": loan_cluster(loan_idx, values, replicates=replicates, seed=s),
            "month_block": month_block(month_idx, values, replicates=replicates, seed=s),
            "two_way": two_way(loan_idx, month_idx, values, replicates=replicates, seed=s),
        }
        for method, d in draws.items():
            interval = summarize(d, estimate, method)
            hits[method] += int(interval.low <= 0.0 <= interval.high)
            widths[method].append(interval.high - interval.low)
    return {
        "design": {
            "loans": loans,
            "months": months,
            "sd_loan": sd_loan,
            "sd_month": sd_month,
            "sd_noise": sd_noise,
            "simulations": simulations,
            "replicates": replicates,
            "seed": seed,
        },
        "coverage": {k: v / simulations for k, v in hits.items()},
        "mean_width": {k: float(np.mean(v)) for k, v in widths.items()},
        "nominal": 0.95,
    }
