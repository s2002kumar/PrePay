"""Derived behavioral features for the reliability-program candidates (opt-in; ADR 0010).

They use the same information as the base contract: loan terms and month-end rates through
``t-1``. They aren't part of :data:`prepay.features.spec.FEATURES`, so the gold panel and the
sealed primary run are untouched. One function computes them for panel rows (history) and for
state-machine rows (scenarios), so historical vs scenario parity holds by construction.

- ``new_opportunity_bps``: lowest matched-term month-end rate seen in ``[fp-1, t-2]`` (``fp`` =
  first payment month) minus the rate at the end of ``t-1``, in bp. Positive when the market is
  below every rate the borrower has seen since origination. That is a refinancing opportunity the
  loan has never had, unlike ``burnout_months``, which only counts past opportunities. 0 at age 1.
- ``new_low_bps``: lowest month-end rate in ``[t-61, t-2]`` minus the rate at the end of
  ``t-1``, in bp. Positive at a new five-year low (the "media effect"). NaN without a full
  lookback.
- ``payment_saving_pct``: ``100 * (1 - A(market) / A(note))``, the percentage cut in the level
  monthly payment from refinancing the remaining term at the ``t-1`` market rate. It depends on
  the rate level the way borrower economics do. That makes it a defensible alternative to raw
  rate levels, which act as era proxies in the training data (RELIABILITY_PLAN §3).
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from prepay.arrays import BoolArray, FloatArray, IntArray
from prepay.features.batch import PanelBatch
from prepay.features.machine import RatePath
from prepay.finance.amortization import level_payment

DERIVED_VERSION = "1"
DERIVED_NUMERIC = ("new_opportunity_bps", "new_low_bps", "payment_saving_pct")
NEW_LOW_LOOKBACK_MONTHS = 60


def _series(rates: RatePath, short: bool) -> FloatArray:
    return rates.rate_15y if short else rates.rate_30y


def _new_opportunity(
    rates: RatePath, target: IntArray, first_payment: IntArray, short: BoolArray
) -> FloatArray:
    out = np.zeros(target.shape[0])
    for series_short in (False, True):
        series = _series(rates, series_short)
        rows = np.nonzero(short == series_short)[0]
        if rows.size == 0:
            continue
        # The window starts at fp-1, or at the first month of the path for older loans.
        start = np.maximum(first_payment[rows] - 1 - rates.first_month, 0)
        end = target[rows] - 2 - rates.first_month  # inclusive index of t-2
        current = series[target[rows] - 1 - rates.first_month]
        # One running-minimum row per distinct window start (a few hundred months at most):
        # running[k, j] = min(series[starts[k] .. starts[k] + j]).
        starts, inverse = np.unique(start, return_inverse=True)
        running = np.full((starts.shape[0], series.shape[0]), np.nan)
        for k, s in enumerate(starts.tolist()):
            running[k, : series.shape[0] - s] = np.fmin.accumulate(series[s:])
        span = end - start
        prior_min = np.where(span >= 0, running[inverse.reshape(-1), np.maximum(span, 0)], current)
        out[rows] = (prior_min - current) * 100.0
    return out


def _new_low(rates: RatePath, target: IntArray, short: BoolArray) -> FloatArray:
    out = np.full(target.shape[0], np.nan)
    lookback = NEW_LOW_LOOKBACK_MONTHS
    for series_short in (False, True):
        series = _series(rates, series_short)
        # prior_min[i] = min(series[i-60 .. i-1]); index i is the month of t-1.
        prior_min = np.full(series.shape, np.nan)
        for i in range(lookback, series.shape[0]):
            prior_min[i] = series[i - lookback : i].min()
        rows = short == series_short
        index = target[rows] - 1 - rates.first_month
        out[rows] = (prior_min[index] - series[index]) * 100.0
    return out


def derived_features(
    rates: RatePath,
    target_month: IntArray,
    first_payment_month: IntArray,
    short_term: BoolArray,
    note_rate_pct: FloatArray,
    remaining_payments: FloatArray,
    market_rate_t1: FloatArray,
) -> dict[str, FloatArray]:
    """Derived columns for rows ``(loan, t)``; every input is known at the end of ``t-1``."""
    target = np.asarray(target_month, dtype=np.int64)
    if np.any(target - 1 > rates.last_month) or np.any(target - 1 < rates.first_month):
        raise ValueError("derived features need the month-end rate of t-1 on the path")
    first_payment = np.asarray(first_payment_month, dtype=np.int64)
    short = np.asarray(short_term, dtype=bool)
    remaining = np.maximum(np.asarray(remaining_payments, dtype=np.float64), 1.0)
    note = np.asarray(note_rate_pct, dtype=np.float64) / 100.0
    market = np.asarray(market_rate_t1, dtype=np.float64) / 100.0
    with np.errstate(invalid="ignore", divide="ignore"):
        saving = 100.0 * (
            1.0 - level_payment(1.0, market, remaining) / level_payment(1.0, note, remaining)
        )
    saving = np.where(np.isfinite(market) & np.isfinite(note), saving, np.nan)
    return {
        "new_opportunity_bps": _new_opportunity(rates, target, first_payment, short),
        "new_low_bps": _new_low(rates, target, short),
        "payment_saving_pct": np.asarray(saving, dtype=np.float64),
    }


def augment(batch: PanelBatch, rates: RatePath) -> PanelBatch:
    """The batch with :data:`DERIVED_NUMERIC` columns added from its own base features.

    Works for gold-panel rows and for state-machine rows alike, which is what makes parity hold.
    A batch that already carries the columns is returned unchanged.
    """
    if all(name in batch.features for name in DERIVED_NUMERIC):
        return batch
    f = batch.features
    age = np.asarray(f["loan_age"], dtype=np.float64).astype(np.int64)
    extra = derived_features(
        rates,
        batch.target_month,
        batch.target_month - age + 1,
        np.asarray(f["term_bucket"], dtype=object) == "15y",
        np.asarray(f["note_rate_pct"], dtype=np.float64),
        np.asarray(f["remaining_payments"], dtype=np.float64),
        np.asarray(f["market_rate_t1"], dtype=np.float64),
    )
    return replace(batch, features={**f, **extra})
