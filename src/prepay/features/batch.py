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
    #: Optional integer code per row, equal exactly when ``loan_id`` is equal. Readers that can
    #: produce it cheaply do; otherwise :meth:`clusters` derives it.
    loan_code: IntArray | None = None

    @property
    def rows(self) -> int:
        return int(self.target_month.shape[0])

    def clusters(self) -> IntArray:
        """Dense loan codes ``0..n_loans-1`` for loan-clustered statistics."""
        key = self.loan_id if self.loan_code is None else self.loan_code
        _, codes = np.unique(key, return_inverse=True)
        return np.asarray(codes, dtype=np.int64).reshape(-1)

    def slice(self, start: int, stop: int) -> PanelBatch:
        """Rows ``[start, stop)`` as views; nothing is copied."""
        return PanelBatch(
            loan_id=self.loan_id[start:stop],
            target_month=self.target_month[start:stop],
            outcome_class=self.outcome_class[start:stop],
            exposure_upb=self.exposure_upb[start:stop],
            features={name: values[start:stop] for name, values in self.features.items()},
            loan_code=None if self.loan_code is None else self.loan_code[start:stop],
        )
