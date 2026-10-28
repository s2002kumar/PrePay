"""Calendar months as integers: the canonical period type across ingest, features and models.

A month is ``year * 12 + (month - 1)``, so consecutive months differ by exactly 1 and month
arithmetic is integer arithmetic. Source files use ``YYYYMM``; reports use ``YYYY-MM``.
Months carry no time zone: a month index denotes the whole calendar month.
"""

from __future__ import annotations

import datetime as dt
import re

import numpy as np
import numpy.typing as npt

_YYYYMM = re.compile(r"(?P<y>\d{4})(?P<m>0[1-9]|1[0-2])")
_ISO = re.compile(r"(?P<y>\d{4})-(?P<m>0[1-9]|1[0-2])")


def month(year: int, month_of_year: int) -> int:
    if not 1 <= month_of_year <= 12:
        raise ValueError(f"month_of_year must be 1..12, got {month_of_year}")
    return year * 12 + month_of_year - 1


def parse_yyyymm(text: str) -> int:
    """Parse a source ``YYYYMM`` string."""
    match = _YYYYMM.fullmatch(text)
    if match is None:
        raise ValueError(f"not a YYYYMM month: {text!r}")
    return month(int(match["y"]), int(match["m"]))


def parse_iso(text: str) -> int:
    """Parse a report-style ``YYYY-MM`` string."""
    match = _ISO.fullmatch(text)
    if match is None:
        raise ValueError(f"not a YYYY-MM month: {text!r}")
    return month(int(match["y"]), int(match["m"]))


def year_of(m: int) -> int:
    return m // 12


def month_of_year(m: int) -> int:
    return m % 12 + 1


def to_yyyymm(m: int) -> str:
    return f"{year_of(m):04d}{month_of_year(m):02d}"


def to_iso(m: int) -> str:
    return f"{year_of(m):04d}-{month_of_year(m):02d}"


def of_date(day: dt.date) -> int:
    return month(day.year, day.month)


def last_day(m: int) -> dt.date:
    """Last calendar day of month ``m``."""
    following = m + 1
    return dt.date(year_of(following), month_of_year(following), 1) - dt.timedelta(days=1)


def yyyymm_array(months: npt.ArrayLike) -> npt.NDArray[np.str_]:
    """Vectorized ``YYYYMM`` formatting for integer month arrays."""
    m = np.asarray(months, dtype=np.int64)
    return np.char.add(
        np.char.zfill((m // 12).astype(str), 4), np.char.zfill((m % 12 + 1).astype(str), 2)
    )
