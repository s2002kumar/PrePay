"""Contractual level-payment amortization for fixed-rate loans (pure, vectorized float64).

Implements ``docs/FINANCIAL_CONVENTIONS.md`` §2. Units: balances in currency units (USD),
``annual_rate`` as a decimal fraction per year (0.065 = 6.5%/yr), payment counts in months.
All functions broadcast over arrays of loan lines and perform no I/O.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from prepay.arrays import FloatArray


def level_payment(
    balance: npt.ArrayLike, annual_rate: npt.ArrayLike, remaining_payments: npt.ArrayLike
) -> FloatArray:
    """Level monthly payment ``A`` that retires ``balance`` over ``remaining_payments`` months.

    ``A = B * i / (1 - (1 + i)^-n)`` with ``i = annual_rate / 12``; for ``i = 0``, ``A = B / n``.
    The annuity denominator is evaluated as ``-expm1(-n * log1p(i))`` so that very small
    positive rates do not lose precision to cancellation. Lines with zero balance or no
    remaining payments return 0.
    """
    b = np.asarray(balance, dtype=np.float64)
    i = np.asarray(annual_rate, dtype=np.float64) / 12.0
    n = np.asarray(remaining_payments, dtype=np.float64)
    live = (b > 0.0) & (n >= 1.0)
    n_safe = np.where(live, n, 1.0)
    positive_rate = i > 0.0
    i_safe = np.where(positive_rate, i, 1.0)
    annuity_denominator = -np.expm1(-n_safe * np.log1p(i_safe))
    payment = np.where(positive_rate, b * i_safe / annuity_denominator, b / n_safe)
    return np.asarray(np.where(live, payment, 0.0), dtype=np.float64)


def contractual_month(
    balance: npt.ArrayLike, annual_rate: npt.ArrayLike, remaining_payments: npt.ArrayLike
) -> tuple[FloatArray, FloatArray]:
    """Return ``(contractual_interest, scheduled_principal)`` for one month.

    ``I_t = B_t * c / 12`` is accrued contractual interest, not a cash receipt.
    ``SP_t = min(B_t, max(0, A - I_t))``; at the final contractual payment (``n_t = 1``) the
    scheduled principal is exactly ``B_t`` so the loan amortizes to zero.
    """
    b = np.asarray(balance, dtype=np.float64)
    c = np.asarray(annual_rate, dtype=np.float64)
    n = np.asarray(remaining_payments, dtype=np.int64)
    interest = b * (c / 12.0)
    payment = level_payment(b, c, n)
    scheduled = np.minimum(b, np.maximum(0.0, payment - interest))
    scheduled = np.where(n == 1, b, scheduled)
    scheduled = np.where(b > 0.0, scheduled, 0.0)
    return np.asarray(interest, dtype=np.float64), np.asarray(scheduled, dtype=np.float64)


def contractual_balance_after(
    balance: float, annual_rate: float, term_months: int, payments_made: int
) -> float:
    """Closed-form remaining balance after ``payments_made`` level payments with no prepayment.

    ``B_k = B_0 * ((1+i)^N - (1+i)^k) / ((1+i)^N - 1)`` for ``i > 0``; linear for ``i = 0``.
    Used as an analytical cross-check of the month-by-month recursion.
    """
    if not 0 <= payments_made <= term_months:
        raise ValueError("payments_made must lie in [0, term_months]")
    i = annual_rate / 12.0
    if i == 0.0:
        return balance * (term_months - payments_made) / term_months
    growth_n = np.expm1(term_months * np.log1p(i))
    growth_k = np.expm1(payments_made * np.log1p(i))
    return float(balance * (growth_n - growth_k) / growth_n)
