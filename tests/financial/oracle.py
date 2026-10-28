"""Independent high-precision reference oracle for the finance engine.

Written separately from ``prepay.finance`` on purpose: scalar loops, ``decimal.Decimal`` with 60
significant digits, the direct annuity power ``(1 + i) ** -n`` instead of log1p/expm1, and its own
recovery bookkeeping. Float inputs are converted exactly (``Decimal(float)``), so the oracle
computes the exact-arithmetic answer for the same binary inputs the engine receives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, localcontext

PRECISION = 60
ZERO = Decimal(0)
ONE = Decimal(1)
TWELVE = Decimal(12)


@dataclass
class OracleMonth:
    beginning: Decimal
    interest: Decimal
    scheduled: Decimal
    prepaid: Decimal
    disposed: Decimal
    ending: Decimal


@dataclass
class OracleLedger:
    months: list[OracleMonth]
    recoveries: dict[int, Decimal] = field(default_factory=dict)  # month index -> amount
    losses: dict[int, Decimal] = field(default_factory=dict)


def oracle_line(
    balance: float,
    annual_rate: float,
    remaining_payments: int,
    prepay: list[float],
    credit: list[float],
    *,
    severity: float = 0.0,
    recovery_lag_months: int = 0,
) -> OracleLedger:
    """Exact expected ledger for one loan line over ``len(prepay)`` months."""
    if len(prepay) != len(credit):
        raise ValueError("hazard paths must have equal length")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        b = Decimal(balance)
        i = Decimal(annual_rate) / TWELVE
        sev = Decimal(severity)
        ledger = OracleLedger(months=[])
        for t, (p_raw, d_raw) in enumerate(zip(prepay, credit, strict=True)):
            n = remaining_payments - t
            p, d = Decimal(p_raw), Decimal(d_raw)
            interest = b * i
            if b == ZERO or n <= 0:
                scheduled = ZERO
            elif n == 1:
                scheduled = b
            elif i == ZERO:
                scheduled = b / Decimal(n)
            else:
                payment = b * i / (ONE - (ONE + i) ** (-n))
                scheduled = min(b, max(ZERO, payment - interest))
            remaining_exposure = b - scheduled
            prepaid = p * remaining_exposure
            disposed = d * remaining_exposure
            ending = remaining_exposure - prepaid - disposed
            ledger.months.append(OracleMonth(b, interest, scheduled, prepaid, disposed, ending))
            due = t + recovery_lag_months
            ledger.recoveries[due] = ledger.recoveries.get(due, ZERO) + (ONE - sev) * disposed
            ledger.losses[due] = ledger.losses.get(due, ZERO) + sev * disposed
            b = ending
        return ledger


def oracle_payment(balance: float, annual_rate: float, payments: int) -> Decimal:
    """Exact level payment for a fresh loan."""
    with localcontext() as ctx:
        ctx.prec = PRECISION
        b = Decimal(balance)
        i = Decimal(annual_rate) / TWELVE
        if i == ZERO:
            return b / Decimal(payments)
        return b * i / (ONE - (ONE + i) ** (-payments))
