"""Deterministic feature state machine for historical and hypothetical rate paths.

Given static loan attributes and a month-end rate path, :func:`compute_features` produces the
feature columns of :data:`prepay.features.spec.FEATURES` for any (loan, target month) pairs. It
never sees borrower outcomes: a scenario is just a rate path whose months after ``t0`` are
hypothetical. On historical paths the output must equal the dbt gold panel (parity-tested).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, replace

import numpy as np
import numpy.typing as npt

from prepay import periods
from prepay.arrays import BoolArray, FloatArray, IntArray

ObjectArray = npt.NDArray[np.object_]

BURNOUT_THRESHOLD_BPS = 50.0
PMMS_METHOD_CHANGE = dt.date(2022, 11, 17)
TERM_15Y_MAX = 180
TERM_20Y_MAX = 240

_REGIONS = {
    "northeast": ("CT", "ME", "MA", "NH", "RI", "VT", "NJ", "NY", "PA"),
    "midwest": ("IL", "IN", "MI", "OH", "WI", "IA", "KS", "MN", "MO", "NE", "ND", "SD"),
    "south": (
        "DE",
        "DC",
        "FL",
        "GA",
        "MD",
        "NC",
        "SC",
        "VA",
        "WV",
        "AL",
        "KY",
        "MS",
        "TN",
        "AR",
        "LA",
        "OK",
        "TX",
    ),
    "west": ("AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY", "AK", "CA", "HI", "OR", "WA"),
}
_STATE_REGION = {state: region for region, states in _REGIONS.items() for state in states}


def census_region(state: str | None) -> str | None:
    if state is None:
        return None
    return _STATE_REGION.get(state, "territory")


@dataclass(frozen=True, slots=True)
class LoanStatics:
    """Static attributes of ``n`` loans. Missing numeric values are NaN, missing codes None."""

    note_rate_pct: FloatArray
    original_loan_term: IntArray
    first_payment_month: IntArray
    maturity_month: IntArray
    original_upb: FloatArray
    credit_score: FloatArray
    original_ltv: FloatArray
    original_dti: FloatArray
    mi_pct: FloatArray
    number_of_units: FloatArray
    number_of_borrowers: FloatArray
    loan_purpose: ObjectArray
    occupancy_status: ObjectArray
    channel: ObjectArray
    first_time_homebuyer: ObjectArray
    property_type: ObjectArray
    property_state: ObjectArray

    @property
    def count(self) -> int:
        return int(self.note_rate_pct.shape[0])

    def take(self, index: IntArray) -> LoanStatics:
        return LoanStatics(**{name: getattr(self, name)[index] for name in self.__slots__})


@dataclass(frozen=True, slots=True)
class RatePath:
    """Month-end as-of mortgage rates (percent/yr) for consecutive months from ``first_month``.

    ``application_based`` marks months whose observation follows Freddie Mac's 2022-11-17 PMMS
    method change; hypothetical months appended by :meth:`extended` are marked True because they
    represent the current method.
    """

    first_month: int
    rate_30y: FloatArray
    rate_15y: FloatArray
    application_based: BoolArray
    hypothetical_from: int | None = None  # first month that is a scenario, not history

    @property
    def last_month(self) -> int:
        return self.first_month + int(self.rate_30y.shape[0]) - 1

    @classmethod
    def from_weekly(
        cls,
        dates_30y: list[dt.date],
        rates_30y: list[float | None],
        dates_15y: list[dt.date],
        rates_15y: list[float | None],
    ) -> RatePath:
        """Month-end as-of path: the last non-missing observation on or before each month end."""
        first = min(periods.of_date(dates_30y[0]), periods.of_date(dates_15y[0]))
        last = max(periods.of_date(dates_30y[-1]), periods.of_date(dates_15y[-1]))
        months = np.arange(first, last + 1)
        ends = np.array([periods.last_day(int(m)).toordinal() for m in months])

        def asof(dates: list[dt.date], values: list[float | None]) -> tuple[FloatArray, IntArray]:
            keep = [(d.toordinal(), v) for d, v in zip(dates, values, strict=True) if v is not None]
            ordinals = np.array([k for k, _ in keep])
            vals = np.array([v for _, v in keep], dtype=np.float64)
            index = np.searchsorted(ordinals, ends, side="right") - 1
            rate = np.where(index >= 0, vals[np.maximum(index, 0)], np.nan)
            observed = np.where(index >= 0, ordinals[np.maximum(index, 0)], -1)
            return rate, observed

        r30, observed_30 = asof(dates_30y, rates_30y)
        r15, _ = asof(dates_15y, rates_15y)
        cutover = PMMS_METHOD_CHANGE.toordinal()
        return cls(first, r30, r15, observed_30 >= cutover)

    def truncated(self, through_month: int) -> RatePath:
        """History known at the end of ``through_month`` (as-of view for scenarios/backtests)."""
        if not self.first_month <= through_month <= self.last_month:
            raise ValueError("through_month outside the rate path")
        keep = through_month - self.first_month + 1
        return replace(
            self,
            rate_30y=self.rate_30y[:keep],
            rate_15y=self.rate_15y[:keep],
            application_based=self.application_based[:keep],
            hypothetical_from=None,
        )

    def extended(self, rate_30y: FloatArray, rate_15y: FloatArray) -> RatePath:
        """Append hypothetical month-end rates for the months after :attr:`last_month`."""
        if rate_30y.shape != rate_15y.shape:
            raise ValueError("scenario 30y and 15y paths must have equal length")
        if np.any(~np.isfinite(rate_30y)) or np.any(~np.isfinite(rate_15y)):
            raise ValueError("scenario rates must be finite")
        return replace(
            self,
            rate_30y=np.concatenate([self.rate_30y, rate_30y]),
            rate_15y=np.concatenate([self.rate_15y, rate_15y]),
            application_based=np.concatenate(
                [self.application_based, np.ones(rate_30y.shape[0], dtype=bool)]
            ),
            hypothetical_from=self.last_month + 1,
        )

    def matched(self, months: IntArray, short_term: BoolArray) -> FloatArray:
        """Rate at the end of each month for each row's matched term (NaN outside the path)."""
        index = np.asarray(months) - self.first_month
        inside = (index >= 0) & (index < self.rate_30y.shape[0])
        safe = np.clip(index, 0, self.rate_30y.shape[0] - 1)
        rate = np.where(short_term, self.rate_15y[safe], self.rate_30y[safe])
        return np.asarray(np.where(inside, rate, np.nan), dtype=np.float64)


def _burnout(
    loans: LoanStatics, loan_index: IntArray, target: IntArray, rates: RatePath
) -> FloatArray:
    out = np.zeros(target.shape[0])
    short = loans.original_loan_term[loan_index] <= TERM_15Y_MAX
    notes = loans.note_rate_pct[loan_index]
    first_payment = loans.first_payment_month[loan_index]
    for series_short in (False, True):
        series = rates.rate_15y if series_short else rates.rate_30y
        prior = np.r_[np.nan, series[:-1]]  # rate at the end of month j-1, indexed by j
        for note in np.unique(notes[short == series_short]):
            rows = (short == series_short) & (notes == note)
            with np.errstate(invalid="ignore"):
                in_money = (note - prior) * 100.0 > BURNOUT_THRESHOLD_BPS
            cumulative = np.cumsum(in_money)

            def cum_at(month: IntArray, cumulative: IntArray = cumulative) -> FloatArray:
                index = month - rates.first_month
                if np.any(index >= cumulative.shape[0]):
                    raise ValueError("target month beyond the rate path")
                return np.asarray(
                    np.where(index >= 0, cumulative[np.maximum(index, 0)], 0), dtype=np.float64
                )

            out[rows] = cum_at(target[rows] - 1) - cum_at(first_payment[rows] - 1)
    return out


def compute_features(
    loans: LoanStatics, rates: RatePath, loan_index: IntArray, target_month: IntArray
) -> dict[str, npt.NDArray[np.float64] | ObjectArray]:
    """Feature columns for rows ``(loans[loan_index[k]], target_month[k])``.

    Every value uses information through ``target_month - 1`` only: static attributes, the
    contract schedule, and month-end rates up to ``t-1`` (which may be hypothetical in a scenario).
    """
    idx = np.asarray(loan_index, dtype=np.int64)
    t = np.asarray(target_month, dtype=np.int64)
    if idx.shape != t.shape:
        raise ValueError("loan_index and target_month must align")
    if np.any(t - 1 > rates.last_month):
        raise ValueError("features for month t need the month-end rate of t-1 on the path")
    term = loans.original_loan_term[idx]
    short = term <= TERM_15Y_MAX
    note = loans.note_rate_pct[idx]
    rate_t1 = rates.matched(t - 1, short)
    rate_t7 = rates.matched(t - 7, short)
    rate_fp = rates.matched(loans.first_payment_month[idx] - 1, short)
    t1_index = np.clip(t - 1 - rates.first_month, 0, rates.application_based.shape[0] - 1)
    borrowers = loans.number_of_borrowers[idx]

    def flag(values: FloatArray) -> FloatArray:
        return np.isnan(values).astype(np.float64)

    def codes(values: ObjectArray) -> ObjectArray:
        return np.asarray(values, dtype=object)

    with np.errstate(invalid="ignore"):
        multiple_borrowers = np.where(np.isnan(borrowers), np.nan, (borrowers > 1).astype(float))
    return {
        "credit_score": loans.credit_score[idx],
        "credit_score_missing": flag(loans.credit_score[idx]),
        "original_ltv": loans.original_ltv[idx],
        "ltv_missing": flag(loans.original_ltv[idx]),
        "original_dti": loans.original_dti[idx],
        "dti_missing": flag(loans.original_dti[idx]),
        "mi_pct": loans.mi_pct[idx],
        "log_original_upb": np.log(loans.original_upb[idx]),
        "note_rate_pct": note,
        "number_of_units": loans.number_of_units[idx],
        "term_bucket": codes(np.where(short, "15y", np.where(term <= TERM_20Y_MAX, "20y", "30y"))),
        "loan_purpose": codes(loans.loan_purpose[idx]),
        "occupancy_status": codes(loans.occupancy_status[idx]),
        "channel": codes(loans.channel[idx]),
        "first_time_homebuyer": codes(loans.first_time_homebuyer[idx]),
        "property_type": codes(loans.property_type[idx]),
        "census_region": codes(
            np.array([census_region(s) for s in loans.property_state[idx]], dtype=object)
        ),
        "multiple_borrowers": multiple_borrowers,
        "month_of_year": codes((t % 12 + 1).astype(object)),
        "loan_age": (t - loans.first_payment_month[idx] + 1).astype(np.float64),
        "remaining_payments": (loans.maturity_month[idx] - t + 1).astype(np.float64),
        "market_rate_t1": rate_t1,
        "incentive_bps": (note - rate_t1) * 100.0,
        "rate_change_6m_bps": (rate_t1 - rate_t7) * 100.0,
        "burnout_months": _burnout(loans, idx, t, rates),
        "sato_bps": (note - rate_fp) * 100.0,
        "pmms_application_based": rates.application_based[t1_index].astype(np.float64),
    }
