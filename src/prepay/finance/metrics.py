"""Pool-level horizon metrics derived from a :class:`PoolLedger` (FINANCIAL_CONVENTIONS §4-5).

Rates with a zero denominator are undefined and returned as NaN rather than zero.
WAL figures are returned as ``None`` when the ledger does not cover the cash flows the
estimand needs (finite-horizon truncation is never reported as full-life WAL).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prepay.finance.amortization import FloatArray
from prepay.finance.ledger import CONSERVATION_RTOL, PoolLedger
from prepay.finance.rates import cpr_from_smm


def _safe_ratio(numerator: FloatArray, denominator: FloatArray) -> FloatArray:
    out = np.full(numerator.shape, np.nan)
    np.divide(numerator, denominator, out=out, where=denominator > 0.0)
    return out


def smm_model(ledger: PoolLedger) -> FloatArray:
    """Model voluntary-payoff principal exit rate ``sum(PP_t) / sum(R_t)`` per month."""
    return _safe_ratio(ledger.voluntary_prepay_principal, ledger.balance_after_scheduled)


def cpr_model(ledger: PoolLedger) -> FloatArray:
    """``CPR_model(t) = 1 - (1 - SMM_model(t))^12`` (full voluntary payoffs only)."""
    return cpr_from_smm(smm_model(ledger))


def credit_exit_rate(ledger: PoolLedger) -> FloatArray:
    """Monthly credit-disposition exposure exit rate ``sum(DC_t) / sum(R_t)``, kept separate."""
    return _safe_ratio(ledger.credit_exit_principal, ledger.balance_after_scheduled)


def _month_years(months: int) -> FloatArray:
    return np.arange(1, months + 1, dtype=np.float64) / 12.0


def cash_wal_years(ledger: PoolLedger) -> float | None:
    """Principal-cash WAL ``sum(t/12 * (SP+PP+RC)) / sum(SP+PP+RC)``; ``None`` unless full-life."""
    if not ledger.exposure_resolved:
        return None
    cash = ledger.principal_cash
    total = float(cash.sum())
    if total <= 0.0:
        return None
    return float((_month_years(ledger.months) * cash).sum() / total)


def exposure_exit_wal_years(ledger: PoolLedger) -> float | None:
    """WAL of exposure exits ``(SP+PP+DC)``: a different estimand that includes credit exits.

    Requires all exposure to have exited by the horizon; recoveries may still be pending.
    """
    scale = max(ledger.initial_upb, 1.0)
    if ledger.ending_upb[-1] > CONSERVATION_RTOL * scale:
        return None
    exits = (
        ledger.scheduled_principal
        + ledger.voluntary_prepay_principal
        + ledger.credit_exit_principal
    )
    total = float(exits.sum())
    if total <= 0.0:
        return None
    return float((_month_years(ledger.months) * exits).sum() / total)


@dataclass(frozen=True, slots=True)
class HorizonSummary:
    """Finite-horizon facts reported alongside (never instead of) full-life WAL."""

    months: int
    initial_upb: float
    principal_cash_received: float
    scheduled_principal: float
    voluntary_prepay_principal: float
    recoveries_received: float
    illustrative_credit_loss: float
    contractual_interest_accrued: float
    ending_upb: float
    pending_recoveries: float
    pending_losses: float

    @property
    def principal_returned_fraction(self) -> float:
        return self.principal_cash_received / self.initial_upb if self.initial_upb > 0 else 0.0

    @property
    def unreturned_principal(self) -> float:
        """Principal not yet received as cash nor written off: ending UPB + pending recoveries."""
        return self.ending_upb + self.pending_recoveries


def horizon_summary(ledger: PoolLedger, months: int) -> HorizonSummary:
    """Summarize the first ``months`` months; resolutions after that month count as pending."""
    if not 1 <= months <= ledger.months:
        raise ValueError(f"months must lie in [1, {ledger.months}]")
    window = slice(0, months)
    # Exposure that exited to credit disposition inside the window but has not resolved yet.
    pending_total = float(
        ledger.credit_exit_principal[window].sum()
        - ledger.recoveries_received[window].sum()
        - ledger.illustrative_credit_loss[window].sum()
    )
    # Severity is constant within a projection, so every resolution splits in the same ratio.
    all_recoveries = (
        float(ledger.recoveries_received.sum()) + ledger.pending_recoveries_after_horizon
    )
    all_losses = float(ledger.illustrative_credit_loss.sum()) + ledger.pending_losses_after_horizon
    resolved = all_recoveries + all_losses
    recovery_share = all_recoveries / resolved if resolved > 0.0 else 0.0
    return HorizonSummary(
        months=months,
        initial_upb=ledger.initial_upb,
        principal_cash_received=float(ledger.principal_cash[window].sum()),
        scheduled_principal=float(ledger.scheduled_principal[window].sum()),
        voluntary_prepay_principal=float(ledger.voluntary_prepay_principal[window].sum()),
        recoveries_received=float(ledger.recoveries_received[window].sum()),
        illustrative_credit_loss=float(ledger.illustrative_credit_loss[window].sum()),
        contractual_interest_accrued=float(ledger.contractual_interest_accrued[window].sum()),
        ending_upb=float(ledger.ending_upb[months - 1]),
        pending_recoveries=pending_total * recovery_share,
        pending_losses=pending_total * (1.0 - recovery_share),
    )
