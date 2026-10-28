"""Incentive-response diagnostics (ADR 0007): partial dependence, bin support, shape error."""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np

from prepay.features.batch import PanelBatch
from prepay.finance.rates import cpr_from_smm
from prepay.modeling.diagnostics import bin_support, incentive_response, shape_error
from prepay.modeling.models import HazardModel


class LinearInIncentive(HazardModel):
    """Payoff hazard 1% + 0.002% per bp of incentive, floored at zero: a known response."""

    family: ClassVar[str] = "test_linear"

    def _predict_block(self, batch: PanelBatch) -> np.ndarray:
        incentive = np.asarray(batch.features["incentive_bps"], dtype=np.float64)
        prepay = np.clip(0.01 + 2e-5 * incentive, 0.0, 0.5)
        return np.column_stack([1.0 - prepay, prepay, np.zeros_like(prepay)])

    def to_json(self) -> dict[str, Any]:
        return {"family": self.family}


def _batch(incentive: np.ndarray, outcome: np.ndarray) -> PanelBatch:
    n = incentive.shape[0]
    return PanelBatch(
        loan_id=np.arange(n).astype(str).astype(object),
        target_month=np.full(n, 2019 * 12),
        outcome_class=outcome,
        exposure_upb=np.full(n, 1e5),
        features={"incentive_bps": incentive},
    )


def test_partial_dependence_overrides_incentive_and_keeps_the_input_intact() -> None:
    reference = _batch(np.array([-300.0, 0.0, 250.0]), np.zeros(3, dtype=np.int64))
    report = incentive_response({"m": LinearInIncentive()}, reference, grid=(-100.0, 0.0, 100.0))
    smm = [point["smm"] for point in report["curves"]["m"]]
    np.testing.assert_allclose(smm, [0.008, 0.01, 0.012])
    assert report["curves"]["m"][1]["cpr"] == float(cpr_from_smm(0.01))
    np.testing.assert_array_equal(reference.features["incentive_bps"], [-300.0, 0.0, 250.0])


def test_bin_support_uses_the_b1_edges() -> None:
    incentive = np.array([-250.0, -100.0, -99.9, 0.0, 49.0, 50.0, 199.0, 200.0, 400.0])
    outcome = np.array([1, 0, 0, 0, 1, 0, 0, 1, 1])
    support = {
        row["bin"]: (row["rows"], row["payoffs"]) for row in bin_support(_batch(incentive, outcome))
    }
    assert support["[-inf, -100)"] == (1, 1)
    assert support["[-100, 0)"] == (2, 0)
    assert support["[0, 50)"] == (2, 1)
    assert support["[50, 100)"] == (1, 0)
    assert support["[200, inf)"] == (2, 2)
    assert sum(rows for rows, _ in support.values()) == incentive.shape[0]


def test_shape_error_is_in_percentage_points() -> None:
    curve = [{"cpr": 0.10}, {"cpr": 0.05}]
    truth = [{"cpr": 0.08}, {"cpr": 0.05}]
    np.testing.assert_allclose(shape_error(curve, truth), [2.0, 0.0])
