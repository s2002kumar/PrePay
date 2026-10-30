"""Projection service behind the API: fictional pools, the bundle's model, cached results.

Every projection states three things besides its numbers:

- whether it lies inside the model's training support (ADR 0009 §7 verdict);
- the spread of key results across the bundle's fitted model families (RELIABILITY_PLAN R2:
  not a confidence interval);
- whether credit exits come from the model or from a stated assumption (ADR 0006 §8).

The model in use is always named, and nothing is substituted silently (R3).
"""

from __future__ import annotations

import functools
import logging
import threading
from typing import Any

from prepay import periods
from prepay.api.bundle import NOTICE, DemoBundle
from prepay.api.schemas import (
    CreditIn,
    Deltas,
    ModelRange,
    MonthlyRow,
    ProjectionRequest,
    ProjectionResponse,
    RangeValue,
    ReliabilityOut,
    ScenarioIn,
    ScenarioOut,
    Summary,
)
from prepay.evaluation.cohort import Predictor
from prepay.finance import CreditAssumptions
from prepay.modeling.models import PsaBaseline
from prepay.reliability.credit import CreditAssumption, annual_from_monthly, monthly_from_annual
from prepay.scenarios.pools import Pool, demo_pools
from prepay.scenarios.projection import ScenarioResult, compare, project_pool
from prepay.scenarios.rates import STANDARD_SCENARIOS, RateScenario

log = logging.getLogger(__name__)
SELECTED = "selected"
#: Fitted families whose spread is shown next to the selected model (B0 PSA is a reference).
RANGE_FAMILIES = ("B1_lookup", "B2_logistic", "M1_lightgbm")
RANGE_METRICS = (
    "principal_returned_fraction_12m",
    "principal_returned_fraction_24m",
    "cash_wal_years",
    "ending_upb_horizon_usd",
)
RANGE_NOTE = (
    "Spread of results across the fitted model families under the same scenario and "
    "assumptions. It shows model disagreement, not a confidence interval."
)


class UnknownPoolError(KeyError):
    pass


def to_scenario(spec: ScenarioIn) -> RateScenario:
    return RateScenario(spec.kind, spec.shock_bps, tuple(spec.path_30y_pct))


class ProjectionService:
    def __init__(self, bundle: DemoBundle, *, cache_size: int = 512) -> None:
        self.bundle = bundle
        self.pools: dict[str, Pool] = demo_pools()
        self.model = bundle.run.selected
        self.model_name = self.model.name
        run = bundle.run
        self.models: dict[str, Predictor] = {
            SELECTED: self.model,
            **{name: run.models[name] for name in RANGE_FAMILIES if name in run.models},
        }
        sufficiency = run.manifest.get("credit_sufficiency") or {}
        self.credit_validated = bool(sufficiency.get("credit_hazard_validated"))
        reference = run.models.get("B0_psa")
        # The training-period mean monthly credit-disposition rate: a data-derived constant.
        self.default_credit_hazard = (
            float(reference.credit_rate) if isinstance(reference, PsaBaseline) else 0.0
        )
        self.warm = threading.Event()
        self._project = functools.lru_cache(maxsize=cache_size)(self._compute)

    def credit_hazard(self, credit: CreditIn) -> float | None:
        """Monthly credit hazard to impose, or ``None`` to use the model's (validated) hazard."""
        if credit.annual_cdr_pct is not None:
            return monthly_from_annual(credit.annual_cdr_pct / 100.0)
        return None if self.credit_validated else self.default_credit_hazard

    def credit_description(self, credit: CreditIn) -> str:
        hazard = self.credit_hazard(credit)
        if hazard is None:
            return "model hazard (passed the credit-sufficiency rule, ADR 0006 §8)"
        source = (
            "user-set"
            if credit.annual_cdr_pct is not None
            else "training-period average; the model's credit hazard is not validated (ADR 0006 §8)"
        )
        return f"assumption: constant {annual_from_monthly(hazard):.2%} annual CDR ({source})"

    def _compute(
        self,
        pool_id: str,
        scenario: RateScenario,
        severity: float,
        lag: int,
        model_key: str,
        credit_hazard: float | None,
    ) -> ScenarioResult:
        model = self.models[model_key]
        if credit_hazard is not None:
            model = CreditAssumption(model, credit_hazard)
        return project_pool(
            self.pools[pool_id],
            model,
            self.bundle.rates,
            scenario,
            CreditAssumptions(severity=severity, recovery_lag_months=lag),
            self.bundle.support,
            self.bundle.profile,
        )

    def result(
        self,
        pool_id: str,
        scenario: RateScenario,
        credit: CreditIn,
        model_key: str = SELECTED,
    ) -> ScenarioResult:
        if pool_id not in self.pools:
            raise UnknownPoolError(pool_id)
        return self._project(
            pool_id,
            scenario,
            credit.severity,
            credit.recovery_lag_months,
            model_key,
            self.credit_hazard(credit),
        )

    def warm_cache(self) -> None:
        """Precompute every pool under the standard scenarios, for every family in the range."""
        default = CreditIn()
        for pool_id in self.pools:
            for scenario in STANDARD_SCENARIOS:
                for model_key in self.models:
                    self.result(pool_id, scenario, default, model_key)
        self.warm.set()
        log.info("projection cache warm", extra={"entries": self._project.cache_info().currsize})

    def model_range(
        self, pool_id: str, scenario: RateScenario, credit: CreditIn, horizon: int
    ) -> ModelRange:
        summaries = {
            key: self.result(pool_id, scenario, credit, key).summary(horizon) for key in self.models
        }

        def spread(metric: str) -> RangeValue:
            values = [s[metric] for s in summaries.values() if s[metric] is not None]
            return RangeValue(min=min(values, default=None), max=max(values, default=None))

        names = [self.model_name if key == SELECTED else key for key in summaries]
        return ModelRange(models=names, **{m: spread(m) for m in RANGE_METRICS}, note=RANGE_NOTE)

    def _scenario_out(
        self, result: ScenarioResult, request: ProjectionRequest, scenario: RateScenario
    ) -> ScenarioOut:
        horizon = request.horizon_months
        reliability = result.reliability(horizon)
        return ScenarioOut(
            kind=result.scenario.kind,
            shock_bps=result.scenario.shock_bps,
            label=result.scenario.label,
            summary=Summary(**result.summary(horizon)),
            monthly=[MonthlyRow(**row) for row in result.monthly(horizon)],
            reliability=ReliabilityOut(**reliability) if reliability else None,
            model_range=self.model_range(request.pool_id, scenario, request.credit, horizon),
        )

    def project(self, request: ProjectionRequest) -> ProjectionResponse:
        scenario_a = to_scenario(request.scenario)
        scenario_b = to_scenario(request.compare_to) if request.compare_to is not None else None
        a = self.result(request.pool_id, scenario_a, request.credit)
        b = (
            self.result(request.pool_id, scenario_b, request.credit)
            if scenario_b is not None
            else None
        )
        out_a = self._scenario_out(a, request, scenario_a)
        out_b = self._scenario_out(b, request, scenario_b) if b and scenario_b else None
        warnings = []
        for name, out in (("A", out_a), ("B", out_b)):
            if out is None or out.reliability is None:
                continue
            if out.reliability.verdict != "supported":
                detail = "; ".join(out.reliability.reasons) or "thin training support"
                warnings.append(
                    f"Scenario {name} ({out.label}) is {out.reliability.verdict}: {detail}. "
                    + (
                        "Read the model range, not the point values."
                        if out.reliability.headline == "range"
                        else "Treat the projection as an extrapolation."
                    )
                )
        if "lightgbm" in self.model_name:
            warnings.append(
                "Tree models can respond flatly or non-monotonically to rate shocks "
                "far from their training data."
            )
        pool = self.pools[request.pool_id]
        return ProjectionResponse(
            notice=NOTICE,
            pool_id=request.pool_id,
            as_of=periods.to_iso(pool.as_of_month),
            model=self.model_name,
            assumptions={
                "credit_exits": self.credit_description(request.credit),
                "credit_severity": request.credit.severity,
                "recovery_lag_months": request.credit.recovery_lag_months,
                "timing": "scheduled principal before same-month exits",
                "scenario_timing": "month 1 uses the rate known at the as-of month (history); "
                "a scenario's rates act from month 2",
                "coupon": "contract note rates are fixed; scenarios change incentives only",
                "curtailments": "not modeled",
                "discounting": "none; cash amounts are undiscounted",
                "model_range": RANGE_NOTE,
            },
            a=out_a,
            b=out_b,
            a_minus_b=Deltas(**compare(b, a, request.horizon_months)) if b is not None else None,
            warnings=warnings,
        )

    def pool_summaries(self) -> list[dict[str, Any]]:
        return [pool.summary() for pool in self.pools.values()]
