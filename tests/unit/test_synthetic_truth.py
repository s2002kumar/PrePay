"""The synthetic ground-truth DGP is coherent and has the documented economic shape."""

from __future__ import annotations

import numpy as np
import pytest

from prepay import periods
from prepay.synthetic import rates, truth


def state(
    incentive: float = 0.0,
    age: int = 48,
    burnout: int = 0,
    calendar: int | None = None,
    fico: float = 740.0,
    ltv: float = 80.0,
    size: int = 1,
) -> truth.LoanState:
    return truth.LoanState(
        incentive_bps=np.full(size, incentive),
        age_months=np.full(size, age, dtype=np.int64),
        burnout_months=np.full(size, burnout, dtype=np.int64),
        calendar_month=calendar if calendar is not None else periods.month(2016, 3),
        fico=np.full(size, fico),
        ltv=np.full(size, ltv),
        dti=np.full(size, 36.0),
        original_upb=np.full(size, 250_000.0),
    )


def test_probabilities_form_a_simplex() -> None:
    rng = np.random.default_rng(0)
    s = truth.LoanState(
        incentive_bps=rng.uniform(-500, 500, 1000),
        age_months=rng.integers(1, 360, 1000),
        burnout_months=rng.integers(0, 100, 1000),
        calendar_month=periods.month(2009, 6),
        fico=np.where(rng.random(1000) < 0.1, np.nan, rng.uniform(300, 850, 1000)),
        ltv=rng.uniform(10, 100, 1000),
        dti=rng.uniform(0, 65, 1000),
        original_upb=rng.uniform(2e4, 2e6, 1000),
    )
    p, c, a = truth.outcome_probabilities(s)
    assert np.all((p >= 0) & (c >= 0) & (a >= 0))
    np.testing.assert_allclose(p + c + a, 1.0, atol=1e-12)


def test_refinance_s_curve_increases_with_incentive() -> None:
    incentives = [-300.0, -100.0, 0.0, 50.0, 100.0, 150.0, 250.0]
    prepay = [float(truth.outcome_probabilities(state(i))[0][0]) for i in incentives]
    assert prepay == sorted(prepay)
    assert prepay[-1] > 5 * prepay[2]  # deep in the money is several times at-the-money


def test_turnover_and_peak_speeds_are_economically_plausible() -> None:
    cpr = lambda smm: 1 - (1 - smm) ** 12  # noqa: E731
    at_money = float(truth.outcome_probabilities(state(0.0))[0][0])
    deep = float(truth.outcome_probabilities(state(250.0))[0][0])
    assert 0.04 < cpr(at_money) < 0.12
    assert 0.35 < cpr(deep) < 0.7


def test_burnout_seasoning_and_stress_effects() -> None:
    fresh = truth.outcome_probabilities(state(150.0, burnout=0))[0][0]
    burned = truth.outcome_probabilities(state(150.0, burnout=40))[0][0]
    assert burned < fresh
    young = truth.outcome_probabilities(state(0.0, age=2))[0][0]
    seasoned = truth.outcome_probabilities(state(0.0, age=48))[0][0]
    assert young < seasoned
    calm = truth.outcome_probabilities(state(calendar=periods.month(2016, 3)))[1][0]
    stressed = truth.outcome_probabilities(state(calendar=periods.month(2009, 3)))[1][0]
    assert stressed > 3 * calm
    weak = truth.outcome_probabilities(state(fico=600.0, ltv=95.0))[1][0]
    strong = truth.outcome_probabilities(state(fico=800.0, ltv=60.0))[1][0]
    assert weak > 5 * strong


def test_censoring_is_informative() -> None:
    weak = truth.censoring_probabilities(state(fico=620.0))[0][0]
    strong = truth.censoring_probabilities(state(fico=780.0))[0][0]
    assert weak > strong


def test_draw_categories_matches_probabilities() -> None:
    rng = np.random.default_rng(7)
    n = 200_000
    drawn = truth.draw_categories(rng, np.full(n, 0.2), np.full(n, 0.3))
    counts = np.bincount(drawn, minlength=3) / n
    np.testing.assert_allclose(counts, [0.2, 0.3, 0.5], atol=0.005)


def test_synthetic_rates_are_deterministic_weekly_and_positive() -> None:
    a = rates.generate(1, periods.month(2026, 6))
    b = rates.generate(1, periods.month(2026, 6))
    np.testing.assert_array_equal(a.rate_30y, b.rate_30y)
    assert all(d.weekday() == 3 for d in a.dates)  # Thursdays, like PMMS
    assert a.dates[-1] <= periods.last_day(periods.month(2026, 6))
    assert np.all(a.rate_15y < a.rate_30y)
    assert np.all(a.rate_15y > 0)
    csv = a.to_fred_csv("MORTGAGE30US").splitlines()
    assert csv[0] == "observation_date,MORTGAGE30US"
    assert csv[1].startswith("1999-01-07,")


def test_month_end_asof_uses_last_observation_on_or_before_month_end() -> None:
    weekly = rates.generate(3, periods.month(2000, 3))
    r30, _ = rates.month_end_asof(weekly, periods.month(1999, 1), periods.month(1999, 1))
    january = [
        v
        for d, v in zip(weekly.dates, weekly.rate_30y, strict=True)
        if d.month == 1 and d.year == 1999
    ]
    assert r30[0] == january[-1]
    with pytest.raises(ValueError, match="precede"):
        rates.month_end_asof(weekly, periods.month(1998, 12), periods.month(1999, 1))
