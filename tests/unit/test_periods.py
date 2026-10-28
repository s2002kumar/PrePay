from __future__ import annotations

import datetime as dt

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from prepay import periods


@given(st.integers(1900, 2199), st.integers(1, 12))
def test_round_trips(year: int, month_of_year: int) -> None:
    m = periods.month(year, month_of_year)
    assert periods.parse_yyyymm(periods.to_yyyymm(m)) == m
    assert periods.parse_iso(periods.to_iso(m)) == m
    assert periods.year_of(m) == year
    assert periods.month_of_year(m) == month_of_year


def test_consecutive_months_differ_by_one_across_year_end() -> None:
    assert periods.parse_yyyymm("202101") - periods.parse_yyyymm("202012") == 1


@pytest.mark.parametrize("bad", ["202113", "202100", "2021-1", "20211", "abcdef", ""])
def test_invalid_yyyymm_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="YYYYMM"):
        periods.parse_yyyymm(bad)


def test_invalid_iso_rejected() -> None:
    with pytest.raises(ValueError, match="YYYY-MM"):
        periods.parse_iso("2021/01")
    with pytest.raises(ValueError, match=r"1\.\.12"):
        periods.month(2021, 13)


def test_last_day_handles_leap_years() -> None:
    assert periods.last_day(periods.month(2024, 2)) == dt.date(2024, 2, 29)
    assert periods.last_day(periods.month(2023, 2)) == dt.date(2023, 2, 28)
    assert periods.last_day(periods.month(2023, 12)) == dt.date(2023, 12, 31)
    assert periods.of_date(dt.date(2023, 12, 31)) == periods.month(2023, 12)


def test_vectorized_formatting() -> None:
    months = np.array([periods.month(1999, 1), periods.month(2026, 12)])
    assert periods.yyyymm_array(months).tolist() == ["199901", "202612"]
