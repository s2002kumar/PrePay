"""Ground-truth data-generating process (DGP) for synthetic loan histories.

Month-``t`` outcome probabilities for an at-risk loan are a three-way softmax over
``(prepay, credit, active)`` with the active logit fixed at 0. Every input is information
available at the end of month ``t-1``, the same information set the models are allowed to use.
Because the truth is known exactly, synthetic runs can check whether a fitted model *recovers*
it. That is an engineering check of the pipeline and says **nothing** about accuracy on real
mortgages.

Censoring processes (modification, whole-loan sale, defect) are drawn before the outcome and are
deliberately *informative* (more likely for weaker credit), mirroring MODELING §2's warning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prepay import periods
from prepay.arrays import BoolArray, FloatArray, IntArray

#: Synthetic credit-stress and forbearance windows (fictional calendar, loosely shaped like
#: 2008-2011 and 2020-2021).
STRESS_WINDOW = (periods.month(2008, 1), periods.month(2011, 12))
FORBEARANCE_WINDOW = (periods.month(2020, 4), periods.month(2021, 9))


@dataclass(frozen=True, slots=True)
class Coefficients:
    """Documented DGP coefficients (logit scale unless stated)."""

    prepay_intercept: float = -5.05  # ~0.6%/month (~7% CPR) turnover: seasoned, at the money
    refi_amplitude: float = 2.45  # S-curve height: ~50% CPR deep in the money, unburned
    refi_midpoint_bps: float = 75.0
    refi_width_bps: float = 25.0
    lock_in_slope: float = 0.35  # extra turnover drag when out of the money (per 100 bps)
    seasoning_ramp_months: float = 30.0
    seasoning_weight: float = 1.0
    burnout_per_month: float = 0.035
    burnout_cap: float = 1.6
    seasonality_amplitude: float = 0.18  # peak in June/July
    prepay_fico_per_point: float = 0.003
    prepay_log_size: float = 0.30
    credit_intercept: float = -8.3
    credit_fico_per_point: float = -0.013
    credit_ltv_per_point: float = 0.035
    credit_dti_per_point: float = 0.025
    credit_stress: float = 1.5
    credit_forbearance_relief: float = -1.2
    credit_age_peak_months: float = 40.0
    modification_intercept: float = -8.6
    sale_intercept: float = -9.9
    defect_intercept: float = -10.6


TRUTH = Coefficients()


@dataclass(frozen=True, slots=True)
class LoanState:
    """As-of-``t-1`` covariates for a batch of at-risk loans (arrays of equal length)."""

    incentive_bps: FloatArray  # (note rate - matched-term market rate at end of t-1) * 100
    age_months: IntArray  # loan age in month t (1 = first payment month)
    burnout_months: IntArray  # months through t-1 with incentive > 50 bps
    calendar_month: int  # month index of t
    fico: FloatArray  # NaN when not available
    ltv: FloatArray  # NaN when not available
    dti: FloatArray  # NaN when not available
    original_upb: FloatArray


def _in(window: tuple[int, int], m: int) -> bool:
    return window[0] <= m <= window[1]


def outcome_logits(state: LoanState, c: Coefficients = TRUTH) -> tuple[FloatArray, FloatArray]:
    """Return ``(prepay_logit, credit_logit)``; the active logit is 0."""
    fico = np.where(np.isnan(state.fico), 700.0, state.fico)
    ltv = np.where(np.isnan(state.ltv), 80.0, state.ltv)
    dti = np.where(np.isnan(state.dti), 40.0, state.dti)
    inc = state.incentive_bps
    age = state.age_months.astype(np.float64)

    refi = c.refi_amplitude / (1.0 + np.exp(-(inc - c.refi_midpoint_bps) / c.refi_width_bps))
    lock_in = c.lock_in_slope * np.minimum(inc, 0.0) / 100.0
    seasoning = c.seasoning_weight * np.log(
        np.clip(age, 1.0, c.seasoning_ramp_months) / c.seasoning_ramp_months
    )
    burnout = -np.minimum(c.burnout_per_month * state.burnout_months, c.burnout_cap)
    month_of_year = periods.month_of_year(state.calendar_month)
    seasonal = c.seasonality_amplitude * np.cos(2.0 * np.pi * (month_of_year - 6.5) / 12.0)
    prepay = (
        c.prepay_intercept
        + refi
        + lock_in
        + seasoning
        + burnout
        + seasonal
        + c.prepay_fico_per_point * (fico - 740.0)
        + c.prepay_log_size * np.log(state.original_upb / 250_000.0)
    )

    age_shape = -((np.log(np.maximum(age, 1.0)) - np.log(c.credit_age_peak_months)) ** 2) / 2.0
    credit = (
        c.credit_intercept
        + age_shape
        + c.credit_fico_per_point * (fico - 740.0)
        + c.credit_ltv_per_point * (ltv - 80.0)
        + c.credit_dti_per_point * (dti - 36.0)
        + (c.credit_stress if _in(STRESS_WINDOW, state.calendar_month) else 0.0)
        + (c.credit_forbearance_relief if _in(FORBEARANCE_WINDOW, state.calendar_month) else 0.0)
    )
    return np.asarray(prepay, dtype=np.float64), np.asarray(credit, dtype=np.float64)


def outcome_probabilities(
    state: LoanState, c: Coefficients = TRUTH
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Coherent ``(prepay, credit, active)`` probabilities via a numerically stable softmax."""
    prepay_logit, credit_logit = outcome_logits(state, c)
    top = np.maximum(np.maximum(prepay_logit, credit_logit), 0.0)
    e_p = np.exp(prepay_logit - top)
    e_c = np.exp(credit_logit - top)
    e_a = np.exp(-top)
    total = e_p + e_c + e_a
    return e_p / total, e_c / total, e_a / total


def censoring_probabilities(
    state: LoanState, c: Coefficients = TRUTH
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Monthly ``(modification, whole-loan sale, defect)`` probabilities (informative)."""
    fico = np.where(np.isnan(state.fico), 700.0, state.fico)
    weak = (fico < 660).astype(np.float64)
    stressed = _in(STRESS_WINDOW, state.calendar_month) or _in(
        FORBEARANCE_WINDOW, state.calendar_month
    )
    mod = _sigmoid(c.modification_intercept + 1.3 * weak + (1.4 if stressed else 0.0))
    sale = _sigmoid(np.full(fico.shape, c.sale_intercept) + 0.8 * weak)
    defect = _sigmoid(np.full(fico.shape, c.defect_intercept))
    return mod, sale, defect


def _sigmoid(x: FloatArray) -> FloatArray:
    return np.asarray(1.0 / (1.0 + np.exp(-x)), dtype=np.float64)


def draw_categories(rng: np.random.Generator, *probabilities: FloatArray) -> IntArray:
    """Draw one category per row; returns index into ``probabilities`` or ``len`` for 'none'."""
    u = rng.random(probabilities[0].shape)
    result = np.full(u.shape, len(probabilities), dtype=np.int64)
    cumulative = np.zeros(u.shape)
    unassigned: BoolArray = np.ones(u.shape, dtype=bool)
    for index, p in enumerate(probabilities):
        cumulative = cumulative + p
        hit = unassigned & (u < cumulative)
        result[hit] = index
        unassigned &= ~hit
    return result
