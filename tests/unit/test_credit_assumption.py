"""Credit exits as an explicit assumption (F2): coherent overlay of a model's probabilities."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from prepay.features.batch import PanelBatch
from prepay.modeling.models import IncoherentProbabilityError
from prepay.reliability.credit import (
    CreditAssumption,
    annual_from_monthly,
    monthly_from_annual,
)


class Fixed:
    name = "fixed"

    def __init__(self, p: np.ndarray) -> None:
        self.p = p

    def predict_proba(self, batch: PanelBatch) -> np.ndarray:
        return self.p


def _batch(n: int) -> PanelBatch:
    return PanelBatch(
        loan_id=np.arange(n).astype(object),
        target_month=np.zeros(n, dtype=np.int64),
        outcome_class=np.zeros(n, dtype=np.int64),
        exposure_upb=np.ones(n),
        features={},
    )


@given(
    st.lists(
        st.tuples(st.floats(0.0, 0.3), st.floats(0.0, 0.05)),
        min_size=1,
        max_size=20,
    ),
    st.floats(0.0, 0.05),
)
def test_overlay_is_coherent_and_keeps_the_conditional_payoff(
    rows: list[tuple[float, float]], hazard: float
) -> None:
    prepay = np.array([r[0] for r in rows])
    credit = np.array([r[1] for r in rows])
    p = np.column_stack([1 - prepay - credit, prepay, credit])
    out = CreditAssumption(Fixed(p), hazard).predict_proba(_batch(len(rows)))
    np.testing.assert_allclose(out.sum(axis=1), 1.0, atol=1e-12)
    np.testing.assert_allclose(out[:, 2], hazard)
    conditional = p[:, 1] / (p[:, 0] + p[:, 1])
    np.testing.assert_allclose(out[:, 1] / (out[:, 0] + out[:, 1]), conditional, atol=1e-12)


def test_cdr_conversions_round_trip_and_reject_out_of_range() -> None:
    assert monthly_from_annual(0.0) == 0.0
    assert annual_from_monthly(monthly_from_annual(0.012)) == pytest.approx(0.012)
    with pytest.raises(ValueError, match="annual CDR"):
        monthly_from_annual(0.25)
    with pytest.raises(ValueError, match="monthly credit hazard"):
        CreditAssumption(Fixed(np.zeros((1, 3))), 1.0)


def test_a_certain_model_credit_exit_is_refused() -> None:
    p = np.array([[0.0, 0.0, 1.0]])
    with pytest.raises(IncoherentProbabilityError, match="certain credit exit"):
        CreditAssumption(Fixed(p), 0.01).predict_proba(_batch(1))
    assert CreditAssumption(Fixed(p), 0.01).name == "fixed+credit_assumption"
