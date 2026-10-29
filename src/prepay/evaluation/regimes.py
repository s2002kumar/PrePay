"""Public-rate regimes (ADR 0009 §5) and the rate-history facts behind the failure diagnosis.

Everything here is computed from month-end PMMS rates, a public series. Like every model feature,
the regime of a target month ``t`` uses only rates known at the end of ``t-1``:

- **level band** of the matched-term rate: ``<4.0``, ``4.0-5.5``, ``5.5-7.0``, ``>=7.0`` percent;
- **six-month change**: ``falling`` at or below -50 bp, ``rising`` at or above +50 bp, else
  ``stable``;
- **new low**: the ``t-1`` rate is below every month-end rate in ``t-61 .. t-2``.

:func:`rate_regime_facts` summarizes, per modeling window, how far the rates seen by the models
moved outside the training window's range. It reads no loan data and is safe to publish.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from prepay import periods
from prepay.arrays import BoolArray, FloatArray, IntArray
from prepay.evaluation.segments import Dimension
from prepay.features.batch import PanelBatch
from prepay.features.machine import TERM_15Y_MAX, ObjectArray, RatePath
from prepay.modeling.windows import Window

LEVEL_EDGES = (4.0, 5.5, 7.0)
LEVEL_LABELS = ("<4.0", "4.0-5.5", "5.5-7.0", ">=7.0")
CHANGE_LABELS = ("falling", "stable", "rising")
CHANGE_THRESHOLD_BPS = 50.0
NEW_LOW_LOOKBACK_MONTHS = 60
#: The level that separates the training window into eras (RELIABILITY_PLAN §3.1).
ERA_LEVEL_PCT = 5.5
ERA_BREAK_MONTH = periods.month(2009, 1)


def level_band(rate_pct: FloatArray) -> ObjectArray:
    """Level band label per value; NaN maps to ``"missing"``."""
    index = np.searchsorted(np.asarray(LEVEL_EDGES), rate_pct, side="right")
    labels = np.asarray(LEVEL_LABELS, dtype=object)[np.minimum(index, len(LEVEL_LABELS) - 1)]
    return np.asarray(np.where(np.isnan(rate_pct), "missing", labels), dtype=object)


def change_direction(change_bps: FloatArray) -> ObjectArray:
    """``falling`` / ``stable`` / ``rising`` per six-month change; NaN maps to ``"missing"``."""
    with np.errstate(invalid="ignore"):
        label = np.where(
            change_bps <= -CHANGE_THRESHOLD_BPS,
            "falling",
            np.where(change_bps >= CHANGE_THRESHOLD_BPS, "rising", "stable"),
        )
    return np.asarray(np.where(np.isnan(change_bps), "missing", label), dtype=object)


def _trailing_min(series: FloatArray, lookback: int) -> FloatArray:
    """``out[i] = min(series[i - lookback .. i - 1])``; NaN without a full lookback."""
    out = np.full(series.shape, np.nan)
    for i in range(lookback, series.shape[0]):
        window = series[i - lookback : i]
        if np.all(np.isfinite(window)):
            out[i] = window.min()
    return out


def new_low(rates: RatePath, target_month: IntArray, short_term: BoolArray) -> BoolArray:
    """True where the rate at the end of ``t-1`` is below every month-end rate in ``t-61..t-2``.

    Rows without a full 60-month lookback on the path are False (not a known new low).
    """
    flags = np.zeros(target_month.shape[0], dtype=bool)
    for short, series in ((False, rates.rate_30y), (True, rates.rate_15y)):
        # Index i of ``prior_min`` is month first_month + i; it holds the min over the 60 months
        # before it, so for t-1 at index i it covers t-61 .. t-2.
        prior_min = _trailing_min(series, NEW_LOW_LOOKBACK_MONTHS)
        rows = short_term == short
        index = target_month[rows] - 1 - rates.first_month
        inside = (index >= 0) & (index < series.shape[0])
        safe = np.clip(index, 0, series.shape[0] - 1)
        with np.errstate(invalid="ignore"):
            hit = inside & (series[safe] < prior_min[safe])
        flags[rows] = hit
    return flags


def row_regimes(batch: PanelBatch, rates: RatePath) -> dict[str, ObjectArray]:
    """Level band, six-month change direction and new-low flag for each panel row."""
    short = np.asarray(batch.features["term_bucket"], dtype=object) == "15y"
    low = new_low(rates, batch.target_month, short)
    return {
        "level_band": level_band(np.asarray(batch.features["market_rate_t1"], dtype=np.float64)),
        "rate_change_6m": change_direction(
            np.asarray(batch.features["rate_change_6m_bps"], dtype=np.float64)
        ),
        "new_low": np.asarray(np.where(low, "new_low", "not_new_low"), dtype=object),
    }


def regime_dimensions(rates: RatePath) -> tuple[Dimension, ...]:
    """The ADR 0009 §5 regimes as segment dimensions (D4 calibration-by-regime tables)."""

    def assign(key: str) -> Callable[[PanelBatch], ObjectArray]:
        def labels(batch: PanelBatch) -> ObjectArray:
            return row_regimes(batch, rates)[key]

        return labels

    return (
        Dimension("rate_level_band", LEVEL_LABELS, assign("level_band")),
        Dimension("rate_change_6m", CHANGE_LABELS, assign("rate_change_6m")),
        Dimension("new_low", ("new_low", "not_new_low"), assign("new_low")),
    )


def _short_term(term_months: int) -> bool:
    return term_months <= TERM_15Y_MAX


def _stat(values: FloatArray, reducer: Any) -> float | None:
    finite = values[np.isfinite(values)]
    return round(float(reducer(finite)), 2) if finite.size else None


def rate_regime_facts(
    rates: RatePath,
    windows: Sequence[Window],
    *,
    first_month: int = periods.month(1999, 1),
    train_window: str = "train",
    term_months: int = 360,
) -> dict[str, Any]:
    """Rates seen by the models (end of ``t-1``) in each window, vs the training window's range.

    Windows are clipped to ``[first_month, last month with a known t-1 rate]``. Only the
    matched-term series of a ``term_months`` loan is used (30-year by default).
    """
    series = rates.rate_15y if _short_term(term_months) else rates.rate_30y
    last_target = rates.last_month + 1

    def at(index: IntArray) -> FloatArray:
        safe = np.clip(index, 0, series.shape[0] - 1)
        return np.asarray(np.where(index >= 0, series[safe], np.nan), dtype=np.float64)

    def seen(first: int, last: int) -> tuple[IntArray, FloatArray, FloatArray]:
        start = max(first, first_month, rates.first_month + 1)
        target = np.arange(start, min(last, last_target) + 1, dtype=np.int64)
        index = target - 1 - rates.first_month
        level = at(index)
        change = (level - at(index - 6)) * 100.0
        return target, level, change

    by_name = {w.name: w for w in windows}
    train = by_name[train_window]
    train_target, train_level, _ = seen(train.first, train.last)
    if not np.all(np.isfinite(train_level)):
        raise ValueError("the rate path does not cover the training window")
    low, high = float(np.min(train_level)), float(np.max(train_level))
    short = np.full(1, _short_term(term_months))

    def summary(first: int, last: int) -> dict[str, Any]:
        target, level, change = seen(first, last)
        if target.size == 0:
            return {"months": 0}
        lows = new_low(rates, target, np.repeat(short, target.size))
        return {
            "target_months": f"{periods.to_iso(int(target[0]))}..{periods.to_iso(int(target[-1]))}",
            "months": int(target.size),
            "rate_min_pct": _stat(level, np.min),
            "rate_max_pct": _stat(level, np.max),
            "months_below_train_min": int((level < low).sum()),
            "months_above_train_max": int((level > high).sum()),
            "months_above_era_level": int((level > ERA_LEVEL_PCT).sum()),
            "max_6m_change_bps": _stat(change, np.max),
            "min_6m_change_bps": _stat(change, np.min),
            "new_low_months": int(lows.sum()),
        }

    above = train_level > ERA_LEVEL_PCT
    report_windows = {w.name: summary(w.first, w.last) for w in windows}
    last_window_end = max(w.last for w in windows)
    if last_window_end < last_target:
        report_windows["after_last_window"] = summary(last_window_end + 1, last_target)
    return {
        "source": "month-end as-of PMMS (public); rate known at the end of t-1 for target t",
        "series": "MORTGAGE15US" if _short_term(term_months) else "MORTGAGE30US",
        "train_range_pct": {"min": low, "max": high},
        "train_era_check": {
            "level_pct": ERA_LEVEL_PCT,
            "train_months_above_level": int(above.sum()),
            "of_which_before_2009": int((above & (train_target - 1 < ERA_BREAK_MONTH)).sum()),
        },
        "windows": report_windows,
        "definitions": {
            "level_bands_pct": list(LEVEL_LABELS),
            "change_threshold_bps": CHANGE_THRESHOLD_BPS,
            "new_low": f"t-1 rate below every month-end rate in the {NEW_LOW_LOOKBACK_MONTHS} "
            "months before it",
        },
    }
