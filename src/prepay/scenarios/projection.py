"""Scenario projection: rate path -> point-in-time features -> model hazards -> audited ledger.

The projection always runs to full life (all maturities plus the recovery lag) so cash WAL is a
true full-life figure; horizon views are windows onto that ledger. Hazards come only from loan
attributes and the scenario rate path, never from realized outcomes. The contract note rate is
never modified by a scenario.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from prepay import periods
from prepay.arrays import FloatArray
from prepay.features.batch import PanelBatch
from prepay.features.derived import augment
from prepay.features.machine import RatePath, compute_features
from prepay.finance import (
    CreditAssumptions,
    HazardPaths,
    LoanLines,
    PoolLedger,
    cash_wal_years,
    conservation_residuals,
    cpr_model,
    credit_exit_rate,
    exposure_exit_wal_years,
    horizon_summary,
    project,
)
from prepay.scenarios.pools import Pool
from prepay.scenarios.rates import RateScenario, scenario_path

SUPPORT_CHECKED = ("incentive_bps", "market_rate_t1", "rate_change_6m_bps")


class HazardPredictor(Protocol):
    def predict_proba(self, batch: PanelBatch) -> FloatArray: ...


@dataclass(frozen=True)
class ScenarioResult:
    pool_id: str
    scenario: RateScenario
    as_of_month: int
    rate_path_30y: FloatArray  # month-end scenario rates for t0+1..t0+months (percent)
    ledger: PoolLedger  # full life
    out_of_support_share: FloatArray  # balance-weighted share of rows outside training support

    def summary(self, horizon: int) -> dict[str, Any]:
        months = min(horizon, self.ledger.months)
        window = horizon_summary(self.ledger, months)

        def returned(m: int) -> float | None:
            if m > self.ledger.months:
                return None
            return horizon_summary(self.ledger, m).principal_returned_fraction

        cash_wal = cash_wal_years(self.ledger)
        exit_wal = exposure_exit_wal_years(self.ledger)
        return {
            "horizon_months": months,
            "cash_wal_years": cash_wal,
            "exposure_exit_wal_years": exit_wal,
            "principal_returned_fraction_12m": returned(12),
            "principal_returned_fraction_24m": returned(24),
            "principal_returned_fraction_horizon": window.principal_returned_fraction,
            "contractual_interest_accrued_horizon_usd": window.contractual_interest_accrued,
            "scheduled_principal_horizon_usd": window.scheduled_principal,
            "voluntary_prepay_principal_horizon_usd": window.voluntary_prepay_principal,
            "recoveries_received_horizon_usd": window.recoveries_received,
            "illustrative_credit_loss_horizon_usd": window.illustrative_credit_loss,
            "ending_upb_horizon_usd": window.ending_upb,
            "pending_recoveries_horizon_usd": window.pending_recoveries,
            "max_out_of_support_share_horizon": float(self.out_of_support_share[:months].max()),
        }

    def monthly(self, horizon: int) -> list[dict[str, Any]]:
        months = min(horizon, self.ledger.months)
        ledger = self.ledger
        cpr = cpr_model(ledger)
        credit = credit_exit_rate(ledger)
        cumulative = np.cumsum(ledger.principal_cash)

        def row(k: int) -> dict[str, Any]:
            return {
                "month": periods.to_iso(self.as_of_month + k + 1),
                "market_rate_30y_pct": float(self.rate_path_30y[k]),
                "beginning_upb_usd": float(ledger.beginning_upb[k]),
                "scheduled_principal_usd": float(ledger.scheduled_principal[k]),
                "voluntary_prepay_principal_usd": float(ledger.voluntary_prepay_principal[k]),
                "credit_exit_principal_usd": float(ledger.credit_exit_principal[k]),
                "recoveries_received_usd": float(ledger.recoveries_received[k]),
                "illustrative_credit_loss_usd": float(ledger.illustrative_credit_loss[k]),
                "contractual_interest_accrued_usd": float(ledger.contractual_interest_accrued[k]),
                "ending_upb_usd": float(ledger.ending_upb[k]),
                "cpr_model": _finite(cpr[k]),
                "credit_exit_rate_annualized": _finite(1 - (1 - credit[k]) ** 12),
                "cumulative_principal_returned_fraction": float(cumulative[k] / ledger.initial_upb),
                "out_of_support_share": float(self.out_of_support_share[k]),
            }

        return [row(k) for k in range(months)]


def _finite(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def project_pool(
    pool: Pool,
    model: HazardPredictor,
    history: RatePath,
    scenario: RateScenario,
    credit: CreditAssumptions,
    support: dict[str, dict[str, float]] | None = None,
) -> ScenarioResult:
    t0 = pool.as_of_month
    remaining = pool.remaining_payments
    if np.any(remaining < 1):
        raise ValueError("every pool line needs at least one remaining payment after t0")
    months = int(remaining.max()) + credit.recovery_lag_months
    path = scenario_path(history, t0, months, scenario)
    n = pool.statics.count
    loan_index = np.repeat(np.arange(n), months)
    target = np.tile(np.arange(t0 + 1, t0 + months + 1), n)
    features = compute_features(pool.statics, path, loan_index, target)
    batch = augment(
        PanelBatch(
            loan_id=loan_index.astype(object),
            target_month=target,
            outcome_class=np.zeros(target.size, dtype=np.int64),
            exposure_upb=np.zeros(target.size),
            features=features,
        ),
        path,
    )
    p = np.asarray(model.predict_proba(batch)).reshape(n, months, 3)
    hazards = HazardPaths(prepay=p[:, :, 1], credit=p[:, :, 2], active=p[:, :, 0])
    lines = LoanLines.from_values(pool.current_upb, pool.statics.note_rate_pct / 100.0, remaining)
    projection = project(lines, hazards, credit, months, keep_lines=True)
    assert projection.lines is not None
    if not conservation_residuals(projection.pool).ok:  # project() already raises; belt and braces
        raise ArithmeticError("projection failed conservation")
    outside = np.zeros((n, months), dtype=bool)
    if support:
        for name in SUPPORT_CHECKED:
            bounds = support.get(name)
            if bounds is None:
                continue
            values = np.asarray(features[name], dtype=np.float64).reshape(n, months)
            outside |= (values < bounds["low"]) | (values > bounds["high"])
    balance = projection.lines.beginning_upb
    total = balance.sum(axis=0)
    share = np.divide((balance * outside).sum(axis=0), total, out=np.zeros(months), where=total > 0)
    start = t0 + 1 - path.first_month
    return ScenarioResult(
        pool.pool_id, scenario, t0, path.rate_30y[start : start + months], projection.pool, share
    )


def compare(base: ScenarioResult, alternative: ScenarioResult, horizon: int) -> dict[str, Any]:
    """Scenario minus base, in months, percentage points and dollars (MODELING §7)."""
    a, b = alternative.summary(horizon), base.summary(horizon)

    def delta(key: str, scale: float = 1.0) -> float | None:
        if a[key] is None or b[key] is None:
            return None
        return float((a[key] - b[key]) * scale)

    return {
        "cash_wal_months": delta("cash_wal_years", 12.0),
        "principal_returned_12m_pp": delta("principal_returned_fraction_12m", 100.0),
        "principal_returned_24m_pp": delta("principal_returned_fraction_24m", 100.0),
        "contractual_interest_accrued_horizon_usd": delta(
            "contractual_interest_accrued_horizon_usd"
        ),
        "ending_upb_horizon_usd": delta("ending_upb_horizon_usd"),
    }
