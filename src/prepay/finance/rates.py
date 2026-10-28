"""Prepayment-rate conversions and the PSA benchmark (``docs/FINANCIAL_CONVENTIONS.md`` §4).

All rates are decimal fractions: SMM per month, CPR per year (0.06 = 6% CPR).
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from prepay.arrays import FloatArray

#: 100% PSA ramps CPR by 0.2%/month of age to a 6% plateau at month 30.
PSA_RAMP_PER_MONTH = 0.002
PSA_PLATEAU_CPR = 0.06


def smm_from_cpr(cpr: npt.ArrayLike) -> FloatArray:
    """``SMM = 1 - (1 - CPR)^(1/12)``, evaluated with log1p/expm1 for small rates."""
    c = np.asarray(cpr, dtype=np.float64)
    if np.any((c < 0.0) | (c > 1.0)):
        raise ValueError("CPR must lie in [0, 1]")
    with np.errstate(divide="ignore"):  # CPR = 1 gives log1p(-1) = -inf and SMM = 1 exactly
        return np.asarray(-np.expm1(np.log1p(-c) / 12.0), dtype=np.float64)


def cpr_from_smm(smm: npt.ArrayLike) -> FloatArray:
    """``CPR = 1 - (1 - SMM)^12``. NaN inputs (undefined months) propagate as NaN."""
    s = np.asarray(smm, dtype=np.float64)
    finite = s[np.isfinite(s)]
    if np.any((finite < 0.0) | (finite > 1.0)):
        raise ValueError("SMM must lie in [0, 1]")
    with np.errstate(divide="ignore"):  # SMM = 1 gives log1p(-1) = -inf and CPR = 1 exactly
        return np.asarray(-np.expm1(12.0 * np.log1p(-s)), dtype=np.float64)


def psa_cpr(age_months: npt.ArrayLike, speed: float = 1.0) -> FloatArray:
    """Annual CPR under ``speed`` x 100% PSA at loan age ``age_months`` (age 1 = first payment).

    ``CPR_PSA(age) = speed * min(0.002 * age, 0.06)``. A prepayment benchmark only; it says
    nothing about credit exits, which need a separately defined baseline.
    """
    age = np.asarray(age_months, dtype=np.float64)
    if np.any(age < 0.0):
        raise ValueError("age_months must be non-negative")
    if speed < 0.0:
        raise ValueError("PSA speed must be non-negative")
    cpr = speed * np.minimum(PSA_RAMP_PER_MONTH * age, PSA_PLATEAU_CPR)
    if np.any(cpr > 1.0):
        raise ValueError("PSA speed implies CPR above 100%")
    return np.asarray(cpr, dtype=np.float64)


def psa_smm(age_months: npt.ArrayLike, speed: float = 1.0) -> FloatArray:
    return smm_from_cpr(psa_cpr(age_months, speed))
