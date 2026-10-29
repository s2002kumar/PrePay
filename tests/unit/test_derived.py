"""Derived behavioral features: definitions, point-in-time use and batch augmentation."""

from __future__ import annotations

import numpy as np
import pytest

from prepay import periods
from prepay.features.batch import PanelBatch
from prepay.features.derived import DERIVED_NUMERIC, augment, derived_features
from prepay.features.machine import RatePath
from prepay.finance.amortization import level_payment

START = periods.month(2000, 1)


def _path(r30: list[float]) -> RatePath:
    rates = np.asarray(r30, dtype=np.float64)
    return RatePath(START, rates, rates - 0.5, np.zeros(rates.shape[0], dtype=bool))


def _row(
    path: RatePath, target: int, first_payment: int, note: float = 6.0, short: bool = False
) -> dict[str, float]:
    market = path.matched(np.array([target - 1]), np.array([short]))
    out = derived_features(
        path,
        np.array([target]),
        np.array([first_payment]),
        np.array([short]),
        np.array([note]),
        np.array([300.0]),
        market,
    )
    return {k: float(v[0]) for k, v in out.items()}


def test_new_opportunity_compares_t_minus_1_with_the_lowest_rate_since_origination() -> None:
    #           index: 0    1    2    3    4    5
    path = _path([6.0, 5.0, 5.5, 4.8, 5.2, 5.0])
    fp = START + 1  # first payment month; the window starts at fp - 1 = index 0
    # t-1 = index 3 (4.8): the prior months 0..2 have a low of 5.0 -> 20 bp below.
    assert _row(path, START + 4, fp)["new_opportunity_bps"] == pytest.approx(20.0)
    # t-1 = index 5 (5.0): the lowest prior rate is 4.8 -> -20 bp (not a new opportunity).
    assert _row(path, START + 6, fp)["new_opportunity_bps"] == pytest.approx(-20.0)
    # Age 1 (t = fp): no prior month since origination -> 0.
    assert _row(path, fp, fp)["new_opportunity_bps"] == 0.0


def test_new_opportunity_ignores_rates_before_origination() -> None:
    path = _path([3.0, 6.0, 5.5, 5.0])
    fp = START + 2  # window starts at index 1; the 3.0 at index 0 predates the loan
    assert _row(path, START + 4, fp)["new_opportunity_bps"] == pytest.approx(50.0)


def test_new_low_needs_a_full_lookback_and_measures_the_gap() -> None:
    rates = [5.0] * 60 + [4.7]
    path = _path(rates)
    assert np.isnan(_row(path, START + 60, START + 1)["new_low_bps"])  # t-1 = index 59
    assert _row(path, START + 61, START + 1)["new_low_bps"] == pytest.approx(30.0)


def test_new_low_uses_the_15_year_series_for_short_terms() -> None:
    rates = [5.0] * 60 + [4.7]
    path = RatePath(START, np.array(rates), np.array([4.0] * 60 + [4.2]), np.zeros(61, bool))
    assert _row(path, START + 61, START + 1, short=True)["new_low_bps"] == pytest.approx(-20.0)


def test_payment_saving_is_the_relative_cut_in_the_level_payment() -> None:
    path = _path([4.0] * 12)
    row = _row(path, START + 6, START + 1, note=6.0)
    expected = 100.0 * (1 - level_payment(1.0, 0.04, 300) / level_payment(1.0, 0.06, 300))
    assert row["payment_saving_pct"] == pytest.approx(float(expected), rel=1e-12)
    assert _row(path, START + 6, START + 1, note=4.0)["payment_saving_pct"] == pytest.approx(0.0)
    assert _row(path, START + 6, START + 1, note=3.0)["payment_saving_pct"] < 0.0


def test_payment_saving_depends_on_rate_level_at_fixed_incentive() -> None:
    """The same 100 bp gap is a larger relative saving at lower rate levels."""
    low = _row(_path([3.0] * 12), START + 6, START + 1, note=4.0)["payment_saving_pct"]
    high = _row(_path([7.0] * 12), START + 6, START + 1, note=8.0)["payment_saving_pct"]
    assert low > high > 0.0


def test_derived_features_refuse_months_beyond_the_rate_path() -> None:
    path = _path([5.0] * 6)
    with pytest.raises(ValueError, match="t-1"):
        _row(path, START + 7, START + 1)


def test_augment_adds_columns_once_and_matches_the_direct_computation() -> None:
    path = _path([6.0, 5.0, 5.5, 4.8, 5.2, 5.0, 4.9, 4.6])
    target = np.array([START + 4, START + 7, START + 8])
    age = np.array([4.0, 6.0, 1.0])
    market = path.matched(target - 1, np.zeros(3, dtype=bool))
    features = {
        "loan_age": age,
        "term_bucket": np.array(["30y", "30y", "30y"], dtype=object),
        "note_rate_pct": np.array([6.0, 5.5, 5.0]),
        "remaining_payments": np.array([356.0, 354.0, 360.0]),
        "market_rate_t1": market,
    }
    batch = PanelBatch(
        loan_id=np.array(["a", "b", "c"], dtype=object),
        target_month=target,
        outcome_class=np.zeros(3, dtype=np.int64),
        exposure_upb=np.ones(3),
        features=features,
    )
    augmented = augment(batch, path)
    assert set(DERIVED_NUMERIC) <= set(augmented.features)
    assert augment(augmented, path) is augmented
    direct = derived_features(
        path,
        target,
        target - age.astype(np.int64) + 1,
        np.zeros(3, dtype=bool),
        features["note_rate_pct"],
        features["remaining_payments"],
        market,
    )
    for name in DERIVED_NUMERIC:
        np.testing.assert_array_equal(augmented.features[name], direct[name])
    assert augmented.features["new_opportunity_bps"][2] == 0.0  # age 1
