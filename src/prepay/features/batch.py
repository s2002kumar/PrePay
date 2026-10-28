"""Model input batch: aligned row identifiers, outcomes and feature columns (NumPy only)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from prepay.arrays import FloatArray, IntArray
from prepay.features.machine import ObjectArray


@dataclass(frozen=True, slots=True)
class PanelBatch:
    loan_id: ObjectArray
    target_month: IntArray
    outcome_class: IntArray  # 0 = active, 1 = voluntary payoff, 2 = credit disposition
    exposure_upb: FloatArray
    features: dict[str, npt.NDArray[np.float64] | ObjectArray]

    @property
    def rows(self) -> int:
        return int(self.target_month.shape[0])
