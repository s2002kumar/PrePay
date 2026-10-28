"""Synthetic weekly 30- and 15-year mortgage-rate series in FRED PMMS CSV format.

The path is **fictional**: piecewise-linear anchors loosely shaped like the broad post-1999 rate
cycle (so fictional 2021 and 2023 pools have recognisably different coupons), plus seeded AR(1)
noise. It is not PMMS data and must never be presented as such.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import numpy as np

from prepay import periods
from prepay.arrays import FloatArray

# (YYYY-MM, synthetic 30-year rate in percent per year)
ANCHORS_30Y = (
    ("1999-01", 6.8),
    ("2000-05", 8.5),
    ("2001-10", 6.6),
    ("2003-06", 5.3),
    ("2006-07", 6.8),
    ("2008-12", 5.3),
    ("2010-10", 4.3),
    ("2012-11", 3.4),
    ("2013-09", 4.5),
    ("2016-07", 3.5),
    ("2018-11", 4.9),
    ("2019-09", 3.6),
    ("2021-01", 2.7),
    ("2022-01", 3.2),
    ("2022-10", 7.0),
    ("2023-10", 7.6),
    ("2024-09", 6.1),
    ("2025-01", 7.0),
    ("2026-06", 6.6),
    ("2026-12", 6.4),
)
FIRST_OBSERVATION = dt.date(1999, 1, 7)  # a Thursday, PMMS's publication weekday
SPREAD_15Y = 0.62  # mean 30y - 15y spread, percentage points


@dataclass(frozen=True, slots=True)
class WeeklyRates:
    dates: tuple[dt.date, ...]
    rate_30y: FloatArray  # percent per year
    rate_15y: FloatArray

    def to_fred_csv(self, series: str) -> str:
        """Render one series exactly like ``fredgraph.csv?id=<series>``."""
        values = {"MORTGAGE30US": self.rate_30y, "MORTGAGE15US": self.rate_15y}[series]
        lines = [f"observation_date,{series}"]
        lines += [f"{d.isoformat()},{v:.2f}" for d, v in zip(self.dates, values, strict=True)]
        return "\n".join(lines) + "\n"


def generate(seed: int, last_month: int) -> WeeklyRates:
    """Weekly Thursday observations from 1999-01-07 through the end of ``last_month``."""
    end = periods.last_day(last_month)
    count = (end - FIRST_OBSERVATION).days // 7 + 1
    dates = tuple(FIRST_OBSERVATION + dt.timedelta(weeks=k) for k in range(count))
    anchor_x = np.array(
        [_date_number(periods.last_day(periods.parse_iso(m))) for m, _ in ANCHORS_30Y]
    )
    anchor_y = np.array([y for _, y in ANCHORS_30Y])
    x = np.array([_date_number(d) for d in dates])
    trend = np.interp(x, anchor_x, anchor_y)

    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, 30])))
    noise = np.zeros(count)
    shocks = rng.normal(0.0, 0.045, count)
    for k in range(1, count):
        noise[k] = 0.92 * noise[k - 1] + shocks[k]
    rate_30y = np.round(np.maximum(trend + noise, 1.5), 2)
    spread = SPREAD_15Y + rng.normal(0.0, 0.04, count)
    rate_15y = np.round(np.maximum(rate_30y - spread, 1.0), 2)
    return WeeklyRates(dates=dates, rate_30y=rate_30y, rate_15y=rate_15y)


def month_end_asof(
    rates: WeeklyRates, first_month: int, last_month: int
) -> tuple[FloatArray, FloatArray]:
    """Last weekly observation dated on or before each month's last day (percent per year).

    Index ``k`` corresponds to month ``first_month + k``. This is the generator's own as-of rule;
    the research pipeline derives its rates from the CSV independently.
    """
    ordinals = np.array([d.toordinal() for d in rates.dates])
    months = np.arange(first_month, last_month + 1)
    cut = np.array([periods.last_day(int(m)).toordinal() for m in months])
    index = np.searchsorted(ordinals, cut, side="right") - 1
    if np.any(index < 0):
        raise ValueError("requested months precede the first rate observation")
    return rates.rate_30y[index], rates.rate_15y[index]


def _date_number(day: dt.date) -> float:
    return float(day.toordinal())
