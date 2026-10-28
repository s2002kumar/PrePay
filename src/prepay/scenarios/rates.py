"""Hypothetical mortgage-rate scenarios (ARCHITECTURE §6).

A scenario is a monthly path of month-end market rates after ``t0``. It changes refinancing
incentives, and therefore modeled exits. It never changes a loan's contract note rate. Rates are
percent per year. The 15-year series keeps the last observed 30y-15y spread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from prepay.features.machine import RatePath

MIN_RATE_PCT = 0.5
MAX_RATE_PCT = 20.0
MAX_SHOCK_BPS = 500.0
MAX_CUSTOM_MONTHS = 360


class ScenarioError(ValueError):
    """The requested rate path is outside the economically sensible bounds."""


@dataclass(frozen=True, slots=True)
class RateScenario:
    """``flat`` holds the last observed rates; ``parallel`` shifts them by ``shock_bps`` from the
    first projected month on; ``custom`` uses ``path_30y`` (percent), holding its last value."""

    kind: Literal["flat", "parallel", "custom"]
    shock_bps: float = 0.0
    path_30y: tuple[float, ...] = field(default=())

    @property
    def label(self) -> str:
        if self.kind == "flat":
            return "Flat at last observed"
        if self.kind == "parallel":
            return f"Parallel {self.shock_bps:+.0f} bp"
        return "Custom path"


STANDARD_SCENARIOS = (
    RateScenario("flat"),
    RateScenario("parallel", -200.0),
    RateScenario("parallel", -100.0),
    RateScenario("parallel", 100.0),
    RateScenario("parallel", 200.0),
)


def scenario_path(history: RatePath, t0: int, months: int, scenario: RateScenario) -> RatePath:
    """History through ``t0`` followed by ``months`` hypothetical month-end rates."""
    base = history.truncated(t0)
    last_30y, last_15y = float(base.rate_30y[-1]), float(base.rate_15y[-1])
    if not (np.isfinite(last_30y) and np.isfinite(last_15y)):
        raise ScenarioError("no observed rate at t0")
    spread = last_30y - last_15y
    if scenario.kind == "flat":
        path = np.full(months, last_30y)
    elif scenario.kind == "parallel":
        if abs(scenario.shock_bps) > MAX_SHOCK_BPS:
            raise ScenarioError(f"shock must lie within ±{MAX_SHOCK_BPS:.0f} bp")
        path = np.full(months, last_30y + scenario.shock_bps / 100.0)
    else:
        values = np.asarray(scenario.path_30y, dtype=np.float64)
        if values.size == 0 or values.size > MAX_CUSTOM_MONTHS:
            raise ScenarioError(f"custom path needs 1..{MAX_CUSTOM_MONTHS} monthly values")
        path = np.concatenate([values, np.full(max(months - values.size, 0), values[-1])])[:months]
    path_15y = path - spread
    if (
        not np.all(np.isfinite(path))
        or np.any(path_15y < MIN_RATE_PCT)
        or np.any(path > MAX_RATE_PCT)
    ):
        raise ScenarioError(
            f"scenario rates must stay within [{MIN_RATE_PCT}, {MAX_RATE_PCT}] percent"
        )
    return base.extended(path, path_15y)
