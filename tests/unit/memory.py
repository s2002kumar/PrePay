"""Test helpers for scoring-memory checks (R2 gate G15)."""

from __future__ import annotations

import tracemalloc
from collections.abc import Callable

import numpy as np

from prepay.features.batch import PanelBatch


def repeat_batch(batch: PanelBatch, times: int) -> PanelBatch:
    """``batch`` stacked ``times`` times: a long panel with known per-row answers."""

    def rep(values: np.ndarray) -> np.ndarray:
        return np.concatenate([values] * times)

    return PanelBatch(
        loan_id=rep(batch.loan_id),
        target_month=rep(batch.target_month),
        outcome_class=rep(batch.outcome_class),
        exposure_upb=rep(batch.exposure_upb),
        features={name: rep(values) for name, values in batch.features.items()},
    )


def traced_peak[T](fn: Callable[[], T]) -> tuple[T, int]:
    """``fn()`` and the peak bytes it allocated (NumPy reports its buffers to tracemalloc)."""
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        before = tracemalloc.get_traced_memory()[0]
        result = fn()
        peak = tracemalloc.get_traced_memory()[1] - before
    finally:
        tracemalloc.stop()
    return result, peak
