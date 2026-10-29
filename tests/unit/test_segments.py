"""Pre-registered segment report (ADR 0006 §7): bucket edges, suppression and flags."""

from __future__ import annotations

import numpy as np

from prepay.evaluation.segments import DIMENSIONS, MIN_LOANS, segment_report
from prepay.features.batch import PanelBatch
from prepay.features.spec import CATEGORICAL, NUMERIC

BY_NAME = {d.name: d for d in DIMENSIONS}


def batch(n_loans: int, months: int, *, payoff_every: int) -> PanelBatch:
    n = n_loans * months
    features: dict[str, np.ndarray] = {name: np.full(n, 1.0) for name in NUMERIC}
    features.update(
        loan_age=np.tile(np.arange(30, 30 + months, dtype=float), n_loans),
        incentive_bps=np.zeros(n),
        credit_score=np.full(n, 740.0),
        credit_score_missing=np.zeros(n),
        original_ltv=np.full(n, 75.0),
        ltv_missing=np.zeros(n),
        note_rate_pct=np.full(n, 4.0),
        remaining_payments=np.full(n, 300.0),
    )
    for name in CATEGORICAL:
        features[name] = np.full(n, "P" if name == "loan_purpose" else "30y", dtype=object)
    outcome = np.zeros(n, dtype=np.int64)
    outcome[::payoff_every] = 1
    return PanelBatch(
        loan_id=np.repeat(np.arange(n_loans), months).astype(str).astype(object),
        target_month=np.tile(np.arange(2020 * 12, 2020 * 12 + months), n_loans),
        outcome_class=outcome,
        exposure_upb=np.full(n, 200_000.0),
        features=features,
    )


def labels(dimension: str, **values: np.ndarray) -> list[str]:
    b = batch(1, len(next(iter(values.values()))), payoff_every=10**9)
    for name, column in values.items():
        b.features[name] = column
    return list(BY_NAME[dimension].assign(b))


def test_bucket_edges_follow_the_registered_definitions() -> None:
    incentive = np.array([-250, -200, -100.5, -100, -25, 24.9, 25, 75, 149.9, 150, np.nan])
    assert labels("incentive_bps", incentive_bps=incentive) == [
        "<-200",
        "[-200,-100)",
        "[-200,-100)",
        "[-100,-25)",
        "[-25,25)",
        "[-25,25)",
        "[25,75)",
        "[75,150)",
        "[75,150)",
        ">=150",
        "missing",
    ]
    age = np.array([1, 12, 13, 36, 37, 60, 61, 120, 121], dtype=float)
    assert labels("loan_age_months", loan_age=age) == [
        "1-12", "1-12", "13-36", "13-36", "37-60", "37-60", "61-120", "61-120", "121+"
    ]  # fmt: skip
    ltv = np.array([60, 60.5, 80, 90, 91, 50], dtype=float)
    missing = np.array([0, 0, 0, 0, 0, 1], dtype=float)
    assert labels("original_ltv", original_ltv=ltv, ltv_missing=missing) == [
        "<=60", "60-80", "60-80", "80-90", ">90", "missing"
    ]  # fmt: skip
    score = np.array([659, 660, 719, 720, 760, np.nan])
    assert labels("credit_score", credit_score=score) == [
        "<660", "660-719", "660-719", "720-759", ">=760", "missing"
    ]  # fmt: skip


def test_vintage_is_the_first_payment_year() -> None:
    b = batch(1, 3, payoff_every=10**9)
    b.target_month[:] = [2009 * 12, 2009 * 12 + 11, 2022 * 12]  # Jan 2009, Dec 2009, Jan 2022
    b.features["loan_age"][:] = [1, 13, 1]  # first payments Jan 2009, Dec 2008, Jan 2022
    assert list(BY_NAME["vintage"].assign(b)) == ["2009-2012", "<=2008", "2022+"]


def test_small_cells_are_suppressed_and_bias_is_flagged() -> None:
    b = batch(200, 12, payoff_every=20)  # observed payoff rate 5%
    p = np.column_stack([np.full(b.rows, 0.9), np.full(b.rows, 0.1), np.zeros(b.rows)])
    b.features["loan_purpose"][: 12 * (MIN_LOANS - 1)] = "C"  # 24 loans: below the minimum
    report = segment_report(b, {"selected": p}, replicates=100)
    purpose = report["dimensions"]["loan_purpose"]
    assert purpose["C"] == {"suppressed": f"fewer than {MIN_LOANS} loans"}
    cell = purpose["P"]
    assert cell["loans"] == 200 - (MIN_LOANS - 1)
    model = cell["models"]["selected"]
    assert model["prepay_ae"] == cell["observed_prepay"] / model["expected_prepay"]
    assert 0.4 < model["prepay_ae"] < 0.6  # predicted 10%, observed 5%
    assert model["prepay_ae_interval"]["high"] < 0.8
    assert cell["poorly_served"] is True
    assert "loan_purpose=P" in report["poorly_served_cells"]
    assert model["credit_ae"] is None  # no credit events: not reported


def test_a_calibrated_model_is_not_flagged() -> None:
    b = batch(400, 12, payoff_every=20)
    p = np.column_stack([np.full(b.rows, 0.95), np.full(b.rows, 0.05), np.zeros(b.rows)])
    report = segment_report(b, {"selected": p, "other": p}, replicates=100)
    cell = report["dimensions"]["term"]["30y"]
    assert abs(cell["models"]["selected"]["prepay_ae"] - 1.0) < 1e-12
    assert cell["poorly_served"] is False
    assert report["poorly_served_cells"] == []
    assert cell["cpr_proxy_observed"] == cell["models"]["other"]["cpr_proxy_model"]
