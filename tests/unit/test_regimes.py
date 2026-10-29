"""Public-rate regimes (ADR 0009 §5) and the rate-history facts command."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from prepay import periods
from prepay.cli import main
from prepay.evaluation.regimes import (
    change_direction,
    level_band,
    new_low,
    rate_regime_facts,
)
from prepay.features.machine import RatePath
from prepay.modeling.windows import Window
from prepay.synthetic.rates import generate

START = periods.month(2000, 1)


def _path(rates_30y: list[float]) -> RatePath:
    r30 = np.asarray(rates_30y, dtype=np.float64)
    return RatePath(START, r30, r30 - 0.6, np.zeros(r30.shape[0], dtype=bool))


def test_level_bands_use_closed_lower_edges() -> None:
    values = np.array([3.99, 4.0, 5.49, 5.5, 6.99, 7.0, np.nan])
    assert list(level_band(values)) == [
        "<4.0",
        "4.0-5.5",
        "4.0-5.5",
        "5.5-7.0",
        "5.5-7.0",
        ">=7.0",
        "missing",
    ]


def test_change_direction_thresholds_are_inclusive() -> None:
    values = np.array([-50.0, -49.9, 0.0, 49.9, 50.0, np.nan])
    assert list(change_direction(values)) == [
        "falling",
        "stable",
        "stable",
        "stable",
        "rising",
        "missing",
    ]


def test_new_low_compares_t_minus_1_with_the_prior_60_months() -> None:
    rates = [5.0] * 70 + [4.0, 4.0, 3.9]  # month index 70 is the first drop
    path = _path(rates)
    # Target t uses the rate at t-1: t-1 = START+70 is a new low; START+71 ties it (not below);
    # START+72 is lower again. t-1 = START+30 lacks a full 60-month lookback.
    target = START + 1 + np.array([70, 71, 72, 30, 65])
    short = np.zeros(target.shape[0], dtype=bool)
    assert list(new_low(path, target, short)) == [True, False, True, False, False]


def test_new_low_uses_the_matched_term_series() -> None:
    r30 = np.array([5.0] * 70 + [4.0])
    r15 = np.array([4.0] * 70 + [4.5])  # the 15-year series rises in the same month
    path = RatePath(START, r30, r15, np.zeros(71, dtype=bool))
    target = np.array([START + 71, START + 71])
    assert list(new_low(path, target, np.array([False, True]))) == [True, False]


def test_facts_compare_each_window_with_the_training_range() -> None:
    # 2000-01..2001-12 at 6%, 2002-01..2003-12 at 4%, then 2004 at 2.5% and 2005 at 8%.
    rates = [6.0] * 24 + [4.0] * 24 + [2.5] * 12 + [8.0] * 12
    path = _path(rates)
    windows = (
        Window("train", "train", 0, periods.month(2003, 12)),
        Window("later", "test", periods.month(2004, 1), periods.month(2005, 12)),
    )
    facts = rate_regime_facts(path, windows, first_month=periods.month(2000, 2))
    assert facts["train_range_pct"] == {"min": 4.0, "max": 6.0}
    # Training targets 2000-02..2003-12 see t-1 rates 2000-01..2003-11; 6% months are 2000-01..
    # 2001-12 (24 months), all before 2009.
    assert facts["train_era_check"]["train_months_above_level"] == 24
    later = facts["windows"]["later"]
    # Targets 2004-01..2005-12 see 2003-12 (4%), 12 months of 2.5% and 11 months of 8%.
    assert later["months"] == 24
    assert later["months_below_train_min"] == 12
    assert later["months_above_train_max"] == 11
    assert later["months_above_era_level"] == 11
    assert later["max_6m_change_bps"] == 550.0
    assert later["min_6m_change_bps"] == -150.0
    assert "after_last_window" in facts["windows"]  # the path runs past the last window


def test_rate_regimes_command_reads_fred_csvs(tmp_path: Path) -> None:
    weekly = generate(seed=3, last_month=periods.month(2026, 6))
    pmms = tmp_path / "pmms"
    pmms.mkdir()
    for series in ("MORTGAGE30US", "MORTGAGE15US"):
        (pmms / f"{series}.csv").write_text(weekly.to_fred_csv(series), encoding="utf-8")
    out = tmp_path / "facts.json"
    assert main(["diagnose", "rate-regimes", "--pmms-dir", str(pmms), "--out", str(out)]) == 0
    facts = json.loads(out.read_text(encoding="utf-8"))
    assert set(facts["windows"]) >= {"train", "validation_a", "validation_b", "test_a", "test_c"}
    check = facts["train_era_check"]
    assert 0 <= check["of_which_before_2009"] <= check["train_months_above_level"]
    assert facts["windows"]["train"]["target_months"] == "1999-02..2017-12"
