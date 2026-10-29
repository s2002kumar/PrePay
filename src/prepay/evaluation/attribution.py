"""Behavior vs rate-path error attribution for cohort forecasts (D5, RELIABILITY_PLAN §6).

A forecast made at ``t0`` with the rates known then (**as-of**, flat) can miss for two reasons:
borrowers behaved differently than the model expects, or rates moved. Re-running the same model
with the rates that were later realized (**hindsight**) separates the two exactly:

    total error (as-of - realized)
        = behavioral error (hindsight - realized) + rate-path error (as-of - hindsight)

Only the behavioral part is the model's fault. A forecasting product still has to own the
rate-path part, by showing scenario ranges instead of one path. Realized incidence is
Aalen-Johansen under informative censoring (ADR 0006 §10). A behavioral error is called
*material* only when the hindsight forecast lies outside the censoring bounds as well as outside
the realized estimate's interval. These are pure functions over cohort and run-off reports.
"""

from __future__ import annotations

from typing import Any


def _outside(value: float, low: float, high: float) -> bool:
    return value < low or value > high


def cohort_attribution(cohort_report: dict[str, Any]) -> dict[str, Any]:
    """Per horizon and model: behavioral, rate-path and total error of payoff incidence (pp)."""
    if "horizons" not in cohort_report:
        return {"note": cohort_report.get("note", "no mature horizon")}
    bounds = cohort_report.get("censoring_sensitivity", {})
    bound_horizon = bounds.get("horizon_months")
    incidence = bounds.get("prepay_incidence", {})
    out: dict[str, Any] = {}
    for horizon, entry in cohort_report["horizons"].items():
        realized = float(entry["realized_aalen_johansen_prepay"])
        interval = entry["realized_prepay_interval"]
        at_bound_horizon = horizon == f"{bound_horizon}m" and incidence
        rows: dict[str, Any] = {}
        for name, modes in entry["models"].items():
            hindsight = float(modes["hindsight_rates"]["prepay"])
            as_of = float(modes["as_of_flat_rates"]["prepay"])
            row: dict[str, Any] = {
                "behavioral_error_pp": (hindsight - realized) * 100,
                "rate_path_error_pp": (as_of - hindsight) * 100,
                "total_error_pp": (as_of - realized) * 100,
                "behavioral_outside_realized_interval": _outside(
                    hindsight, float(interval["low"]), float(interval["high"])
                ),
            }
            if at_bound_horizon:
                low = float(incidence["bound_censored_never_pay_off"])
                high = float(incidence["bound_censored_all_pay_off"])
                row["behavioral_outside_censoring_bounds"] = _outside(hindsight, low, high)
                row["behavioral_error_material"] = (
                    row["behavioral_outside_censoring_bounds"]
                    and row["behavioral_outside_realized_interval"]
                )
            rows[name] = row
        out[horizon] = {"realized_prepay": realized, "models": rows}
    return {
        "identity": "total = behavioral (hindsight - realized) + rate path (as-of - hindsight)",
        "unit": "percentage points of cumulative payoff incidence",
        "horizons": out,
    }


def runoff_attribution(runoff_report: dict[str, Any]) -> dict[str, Any]:
    """The same decomposition for the pool factor (pp of t0 balance) and truncated WAL (years)."""
    if "models" not in runoff_report:
        return {"note": runoff_report.get("note", "no run-off")}
    observed = runoff_report["observed"]
    out: dict[str, Any] = {}
    for name, modes in runoff_report["models"].items():
        hindsight, as_of = modes["hindsight_rates"], modes["as_of_flat_rates"]
        factor = {
            horizon: {
                "behavioral_error_pp": (hindsight["pool_factor"][horizon] - value) * 100,
                "rate_path_error_pp": (
                    as_of["pool_factor"][horizon] - hindsight["pool_factor"][horizon]
                )
                * 100,
                "total_error_pp": (as_of["pool_factor"][horizon] - value) * 100,
            }
            for horizon, value in observed["pool_factor"].items()
        }
        out[name] = {
            "pool_factor": factor,
            "wal_truncated_years": {
                "behavioral_error": hindsight["wal_truncated_years"]
                - observed["wal_truncated_years"],
                "rate_path_error": as_of["wal_truncated_years"] - hindsight["wal_truncated_years"],
                "total_error": as_of["wal_truncated_years"] - observed["wal_truncated_years"],
            },
        }
    return {
        "identity": "total = behavioral (hindsight - observed) + rate path (as-of - hindsight)",
        "models": out,
    }
