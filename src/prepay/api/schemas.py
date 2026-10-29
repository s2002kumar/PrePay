"""Strict, bounded request/response contracts for the public demo API (ARCHITECTURE §8).

Every monetary field is in US dollars, every rate field states its unit, and every response
carries ``data_class = "fictional"`` and the demo notice.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from prepay.scenarios.rates import MAX_CUSTOM_MONTHS, MAX_RATE_PCT, MAX_SHOCK_BPS, MIN_RATE_PCT

Rate = Annotated[float, Field(ge=MIN_RATE_PCT, le=MAX_RATE_PCT)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScenarioIn(Strict):
    """A hypothetical month-end 30-year mortgage-rate path after the as-of month."""

    kind: Literal["flat", "parallel", "custom"]
    shock_bps: float = Field(
        0.0,
        ge=-MAX_SHOCK_BPS,
        le=MAX_SHOCK_BPS,
        description="parallel shift in basis points (parallel only)",
    )
    path_30y_pct: list[Rate] = Field(
        default_factory=list,
        max_length=MAX_CUSTOM_MONTHS,
        description="monthly 30y rates in percent (custom only)",
    )

    @model_validator(mode="after")
    def _consistent(self) -> ScenarioIn:
        if self.kind == "custom" and not self.path_30y_pct:
            raise ValueError("custom scenarios need path_30y_pct")
        if self.kind != "custom" and self.path_30y_pct:
            raise ValueError("path_30y_pct is only allowed for custom scenarios")
        if self.kind != "parallel" and self.shock_bps != 0:
            raise ValueError("shock_bps is only allowed for parallel scenarios")
        return self


class CreditIn(Strict):
    """Illustrative credit-resolution assumptions (not calibrated losses)."""

    severity: float = Field(0.35, ge=0.0, le=1.0, description="share of disposed principal lost")
    recovery_lag_months: int = Field(12, ge=0, le=36)
    annual_cdr_pct: float | None = Field(
        None,
        ge=0.0,
        le=20.0,
        description="constant annual credit-disposition rate in percent. It replaces the "
        "model's credit hazard as an explicit assumption; by default the model's hazard is "
        "used only if it passed the credit-sufficiency rule",
    )


class ProjectionRequest(Strict):
    pool_id: str = Field(pattern=r"^[a-z0-9-]{1,64}$")
    scenario: ScenarioIn
    compare_to: ScenarioIn | None = Field(None, description="optional second scenario (B)")
    horizon_months: int = Field(120, ge=1, le=360)
    credit: CreditIn = Field(default_factory=CreditIn)


class MonthlyRow(Strict):
    month: str = Field(description="YYYY-MM")
    market_rate_30y_pct: float
    beginning_upb_usd: float
    scheduled_principal_usd: float
    voluntary_prepay_principal_usd: float
    credit_exit_principal_usd: float
    recoveries_received_usd: float
    illustrative_credit_loss_usd: float
    contractual_interest_accrued_usd: float
    ending_upb_usd: float
    cpr_model: float | None = Field(description="full-payoff-only CPR, fraction per year")
    credit_exit_rate_annualized: float | None
    cumulative_principal_returned_fraction: float
    out_of_support_share: float = Field(description="balance share outside training support")


class Summary(Strict):
    horizon_months: int
    cash_wal_years: float | None
    exposure_exit_wal_years: float | None
    principal_returned_fraction_12m: float | None
    principal_returned_fraction_24m: float | None
    principal_returned_fraction_horizon: float
    contractual_interest_accrued_horizon_usd: float
    scheduled_principal_horizon_usd: float
    voluntary_prepay_principal_horizon_usd: float
    recoveries_received_horizon_usd: float
    illustrative_credit_loss_horizon_usd: float
    ending_upb_horizon_usd: float
    pending_recoveries_horizon_usd: float
    max_out_of_support_share_horizon: float


class ReliabilityOut(Strict):
    """ADR 0009 §7 applicability verdict over the horizon, weighted by projected balance."""

    verdict: Literal["supported", "extrapolating", "unsupported"]
    outside_share: float = Field(description="balance share with a feature outside training")
    sparse_share: float = Field(description="balance share in thinly supported joint cells")
    outside_share_by_feature: dict[str, float]
    reasons: list[str]
    headline: Literal["point", "range"] = Field(
        description="'range' when the point projection should not be read on its own"
    )


class RangeValue(Strict):
    min: float | None
    max: float | None


class ModelRange(Strict):
    """Spread of key results across fitted model families: not a confidence interval."""

    models: list[str]
    principal_returned_fraction_12m: RangeValue
    principal_returned_fraction_24m: RangeValue
    cash_wal_years: RangeValue
    ending_upb_horizon_usd: RangeValue
    note: str


class ScenarioOut(Strict):
    kind: str
    shock_bps: float
    label: str
    summary: Summary
    monthly: list[MonthlyRow]
    reliability: ReliabilityOut | None = None
    model_range: ModelRange | None = None


class Deltas(Strict):
    """Scenario A minus scenario B."""

    cash_wal_months: float | None
    principal_returned_12m_pp: float | None
    principal_returned_24m_pp: float | None
    contractual_interest_accrued_horizon_usd: float | None
    ending_upb_horizon_usd: float | None


class ProjectionResponse(Strict):
    data_class: Literal["fictional"] = "fictional"
    notice: str
    pool_id: str
    as_of: str
    model: str
    assumptions: dict[str, str | float | int]
    a: ScenarioOut
    b: ScenarioOut | None
    a_minus_b: Deltas | None
    warnings: list[str]


class ErrorBody(Strict):
    code: str
    message: str
    details: list[dict[str, object]] = Field(default_factory=list)


class ErrorResponse(Strict):
    error: ErrorBody
