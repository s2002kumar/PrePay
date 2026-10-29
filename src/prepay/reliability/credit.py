"""Credit exits as an explicit scenario assumption (F2; ADR 0006 §8).

A credit-disposition hazard that hasn't passed the ADR 0006 §8 sufficiency rule, or failed
calibration, isn't a forecast. :class:`CreditAssumption` replaces the model's credit probability
with a stated monthly hazard ``d``. It keeps the model's split of the remaining probability
between payoff and staying active::

    p_credit = d
    p_prepay = (1 - d) * p_prepay_model / (1 - p_credit_model)
    p_active = (1 - d) * p_active_model / (1 - p_credit_model)

The result is a valid simplex, and the conditional payoff probability given no credit exit,
``p_prepay / (p_prepay + p_active)``, is exactly the model's. Payoff behavior is untouched; only
the credit exits become an assumption, and it is labeled as one wherever it is used.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prepay.arrays import FloatArray
from prepay.evaluation.cohort import Predictor
from prepay.features.batch import PanelBatch
from prepay.modeling.models import IncoherentProbabilityError, check_simplex

MAX_ANNUAL_CDR = 0.20


def monthly_from_annual(cdr: float) -> float:
    """Constant monthly hazard ``d`` with ``1 - (1 - d)^12 = cdr`` (CDR as a fraction per year)."""
    if not 0.0 <= cdr <= MAX_ANNUAL_CDR:
        raise ValueError(f"annual CDR must lie in [0, {MAX_ANNUAL_CDR}]")
    return float(1.0 - (1.0 - cdr) ** (1.0 / 12.0))


def annual_from_monthly(hazard: float) -> float:
    return float(1.0 - (1.0 - hazard) ** 12)


@dataclass(frozen=True)
class CreditAssumption:
    base: Predictor
    monthly_hazard: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.monthly_hazard < 1.0:
            raise ValueError("the monthly credit hazard must lie in [0, 1)")

    @property
    def name(self) -> str:
        return f"{getattr(self.base, 'name', type(self.base).__name__)}+credit_assumption"

    def predict_proba(self, batch: PanelBatch) -> FloatArray:
        p = np.asarray(self.base.predict_proba(batch), dtype=np.float64)
        no_credit = p[:, 0] + p[:, 1]
        if np.any(no_credit <= 0.0):
            raise IncoherentProbabilityError("the model gives a certain credit exit on some rows")
        scale = (1.0 - self.monthly_hazard) / no_credit
        return check_simplex(
            np.column_stack(
                [p[:, 0] * scale, p[:, 1] * scale, np.full(p.shape[0], self.monthly_hazard)]
            )
        )
