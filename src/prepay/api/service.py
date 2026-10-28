"""Projection service behind the API: fictional pools, the bundle's model, cached results."""

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
    MonthlyRow,
    ProjectionRequest,
    ProjectionResponse,
    ScenarioIn,
    ScenarioOut,
    Summary,
)
from prepay.finance import CreditAssumptions
from prepay.scenarios.pools import Pool, demo_pools
from prepay.scenarios.projection import ScenarioResult, compare, project_pool
from prepay.scenarios.rates import STANDARD_SCENARIOS, RateScenario

log = logging.getLogger(__name__)
OUT_OF_SUPPORT_WARNING = 0.05


class UnknownPoolError(KeyError):
    pass


def to_scenario(spec: ScenarioIn) -> RateScenario:
    return RateScenario(spec.kind, spec.shock_bps, tuple(spec.path_30y_pct))


class ProjectionService:
    def __init__(self, bundle: DemoBundle, *, cache_size: int = 256) -> None:
        self.bundle = bundle
        self.pools: dict[str, Pool] = demo_pools()
        self.model = bundle.run.selected
        self.model_name = self.model.name
        self.warm = threading.Event()
        self._project = functools.lru_cache(maxsize=cache_size)(self._compute)

    def _compute(
        self, pool_id: str, scenario: RateScenario, severity: float, lag: int
    ) -> ScenarioResult:
        return project_pool(
            self.pools[pool_id],
            self.model,
            self.bundle.rates,
            scenario,
            CreditAssumptions(severity=severity, recovery_lag_months=lag),
            self.bundle.support,
        )

    def result(self, pool_id: str, scenario: RateScenario, credit: CreditIn) -> ScenarioResult:
        if pool_id not in self.pools:
            raise UnknownPoolError(pool_id)
        return self._project(pool_id, scenario, credit.severity, credit.recovery_lag_months)

    def warm_cache(self) -> None:
        """Precompute every pool under the standard scenarios with default assumptions."""
        default = CreditIn()
        for pool_id in self.pools:
            for scenario in STANDARD_SCENARIOS:
                self.result(pool_id, scenario, default)
        self.warm.set()
        log.info("projection cache warm", extra={"entries": self._project.cache_info().currsize})

    def _scenario_out(self, result: ScenarioResult, horizon: int) -> ScenarioOut:
        return ScenarioOut(
            kind=result.scenario.kind,
            shock_bps=result.scenario.shock_bps,
            label=result.scenario.label,
            summary=Summary(**result.summary(horizon)),
            monthly=[MonthlyRow(**row) for row in result.monthly(horizon)],
        )

    def project(self, request: ProjectionRequest) -> ProjectionResponse:
        a = self.result(request.pool_id, to_scenario(request.scenario), request.credit)
        b = (
            self.result(request.pool_id, to_scenario(request.compare_to), request.credit)
            if request.compare_to is not None
            else None
        )
        warnings = []
        for result in (r for r in (a, b) if r is not None):
            share = result.summary(request.horizon_months)["max_out_of_support_share_horizon"]
            if share > OUT_OF_SUPPORT_WARNING:
                warnings.append(
                    f"{result.scenario.label}: up to {share:.0%} of projected balance has rate "
                    "features outside the model's training range; treat as extrapolation."
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
                "credit_severity": request.credit.severity,
                "recovery_lag_months": request.credit.recovery_lag_months,
                "timing": "scheduled principal before same-month exits",
                "coupon": "contract note rates are fixed; scenarios change incentives only",
                "curtailments": "not modeled",
                "discounting": "none; cash amounts are undiscounted",
            },
            a=self._scenario_out(a, request.horizon_months),
            b=self._scenario_out(b, request.horizon_months) if b is not None else None,
            a_minus_b=Deltas(**compare(b, a, request.horizon_months)) if b is not None else None,
            warnings=warnings,
        )

    def pool_summaries(self) -> list[dict[str, Any]]:
        return [pool.summary() for pool in self.pools.values()]
