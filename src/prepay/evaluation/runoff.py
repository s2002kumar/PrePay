"""Balance run-off: observed vs projected principal timing for a cohort (ADR 0006 §9).

The cohort is the same as :func:`prepay.evaluation.cohort.build_cohort`: eligible, unmodified
loans active at the end of ``t0``. For month ``k = 1..H`` after ``t0``:

- **Observed balance** ``O[i, k]`` is loan ``i``'s reported current UPB, or 0 after its exit.
- **Projected balance** ``P[i, k] = S_i(k) * b_i(k)``. ``S_i`` is the model's survival under the
  given rate path. ``b_i`` is the contractual amortization of the ``t0`` UPB at the note rate over
  the remaining payments (:func:`prepay.finance.amortization.contractual_month`).
- A **censored** loan (modification, whole-loan sale, RPL securitization, defect, unexplained end)
  leaves both sides from the first month it is no longer observed. Every month-``k`` statistic sums
  over ``U(k)``, the loans still observed in ``k``, divided by their ``t0`` balance.

Month-``k`` principal is decomposed identically on both sides. Exits are counted at the balance
at the start of the month (full payoffs, credit-exit balances). Amortization of continuing loans
is ``O[k-1] - O[k]``, which on the observed side includes curtailments. The engine doesn't model
curtailments, so the observed excess over contractual scheduled principal is reported separately.
Interest, recoveries and losses are not compared (ADR 0006 §9).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import duckdb
import numpy as np
import pyarrow as pa

from prepay import periods
from prepay.arrays import FloatArray, IntArray
from prepay.evaluation.cohort import (
    CENSORED,
    EVENT_C,
    EVENT_O,
    EVENT_P,
    Cohort,
    Predictor,
    Verifiable,
    build_cohort,
    model_hazards,
    survival_before,
)
from prepay.features.machine import LoanStatics, RatePath
from prepay.features.panel import load_statics
from prepay.finance.amortization import contractual_month

REPORT_HORIZONS = (6, 12, 24)


@dataclass(frozen=True)
class RunoffData:
    cohort: Cohort
    upb0: FloatArray  # (n,) balance at the end of t0
    rate: FloatArray  # (n,) note rate, decimal per year
    remaining0: IntArray  # (n,) contractual payments remaining after t0
    observed: FloatArray  # (n, H+1) O[:, 0] = upb0; NaN where not observed (censored or gap)
    exit_month: IntArray  # (n,) k of payoff/credit/maturity exit within H, else 0
    exit_kind: IntArray  # (n,) EVENT_P / EVENT_C / EVENT_O, or CENSORED
    observed_through: IntArray  # (n,) last k in U(k)
    gaps: int  # loan-months missing although the loan was neither exited nor censored


def load_runoff(
    con: duckdb.DuckDBPyConnection,
    t0: int,
    horizon: int,
    loan_ids: np.ndarray,
    statics: LoanStatics,
) -> RunoffData:
    cohort = build_cohort(con, t0, horizon, loan_ids)
    n = cohort.size
    exited = np.isin(cohort.event, (EVENT_P, EVENT_C, EVENT_O))
    exit_month = np.where(exited, cohort.last_month, 0)
    observed_through = np.where(exited, horizon, cohort.last_month)
    members = pa.table(
        {"loan_id": pa.array(list(loan_ids[cohort.loan_index]), pa.string()), "pos": np.arange(n)}
    )
    con.register("runoff_cohort", members)
    try:
        table = con.sql(
            """
            select c.pos, s.period_month - $t0 as k, s.current_upb
            from int_loan_month_state as s
            inner join runoff_cohort as c on s.loan_id = c.loan_id
            where s.period_month between $t0 and $last and s.current_upb is not null
            """,
            params={"t0": t0, "last": t0 + horizon},
        ).to_arrow_table()
    finally:
        con.unregister("runoff_cohort")
    observed = np.full((n, horizon + 1), np.nan)
    observed[
        np.asarray(table["pos"].to_numpy(), dtype=np.int64),
        np.asarray(table["k"].to_numpy(), dtype=np.int64),
    ] = np.asarray(table["current_upb"].cast(pa.float64()).to_numpy(), dtype=np.float64)
    k = np.arange(horizon + 1)[None, :]
    after_exit = exited[:, None] & (k >= exit_month[:, None])
    observed[after_exit] = 0.0
    in_window = k <= observed_through[:, None]
    gaps = int((np.isnan(observed) & in_window).sum())
    observed[~in_window] = np.nan
    return RunoffData(
        cohort=cohort,
        upb0=observed[:, 0].copy(),
        rate=statics.note_rate_pct[cohort.loan_index] / 100.0,
        remaining0=statics.maturity_month[cohort.loan_index] - t0,
        observed=observed,
        exit_month=exit_month,
        exit_kind=np.where(exited, cohort.event, CENSORED),
        observed_through=observed_through,
        gaps=gaps,
    )


def contractual_path(
    upb0: FloatArray, rate: FloatArray, remaining0: IntArray, horizon: int
) -> FloatArray:
    """``b[:, k]``: balance after ``k`` contractual payments, no prepayment, ``(n, H+1)``."""
    b = np.empty((upb0.shape[0], horizon + 1))
    b[:, 0] = upb0
    for k in range(1, horizon + 1):
        _, scheduled = contractual_month(b[:, k - 1], rate, np.maximum(remaining0 - (k - 1), 0))
        b[:, k] = b[:, k - 1] - scheduled
    return b


def observed_flows(data: RunoffData) -> dict[str, FloatArray]:
    """Month-k observed principal by component, ``(n, H)``; NaN outside ``U(k)``."""
    o = data.observed
    start, end = o[:, :-1], o[:, 1:]
    horizon = end.shape[1]
    k = np.arange(1, horizon + 1)[None, :]
    exits_now = data.exit_month[:, None] == k
    payoff = np.where(exits_now & (data.exit_kind[:, None] == EVENT_P), start, 0.0)
    credit = np.where(exits_now & (data.exit_kind[:, None] == EVENT_C), start, 0.0)
    amortization = np.where(
        exits_now & (data.exit_kind[:, None] != EVENT_O), 0.0, start - np.where(exits_now, 0.0, end)
    )
    # Contractual scheduled principal of continuing loans, from their own observed balance.
    remaining = np.maximum(data.remaining0[:, None] - (k - 1), 0)
    _, scheduled = contractual_month(np.nan_to_num(start), data.rate[:, None], remaining)
    continuing = ~exits_now & np.isfinite(end)
    curtailment = np.where(continuing, (start - end) - scheduled, 0.0)
    unobserved = np.isnan(end) & ~exits_now
    return {
        name: np.where(unobserved, np.nan, values)
        for name, values in {
            "payoff": payoff,
            "credit_exit": credit,
            "amortization": amortization,
            "curtailment": curtailment,
        }.items()
    }


def projected_flows(
    p: FloatArray, alive_before: FloatArray, b: FloatArray
) -> dict[str, FloatArray]:
    """Month-k expected principal by component, ``(n, H)``, matching :func:`observed_flows`."""
    start = alive_before * b[:, :-1]
    survive = np.zeros_like(alive_before)
    survive[:, :-1] = alive_before[:, 1:]
    # S(k) = S(k-1) p_active(k) before maturity; after maturity b = 0, so it no longer matters.
    survive[:, -1] = alive_before[:, -1] * p[:, -1, 0]
    return {
        "payoff": start * p[:, :, 1],
        "credit_exit": start * p[:, :, 2],
        "amortization": start - survive * b[:, 1:] - start * (p[:, :, 1] + p[:, :, 2]),
        "balance": survive * b[:, 1:],
    }


def _pool(values: FloatArray, upb0: FloatArray, mask: np.ndarray) -> FloatArray:
    """Per-month sums over ``U(k)`` divided by their t0 balance."""
    numerator = np.where(mask, values, 0.0).sum(axis=0)
    denominator = (mask * upb0[:, None]).sum(axis=0)
    return np.asarray(numerator / denominator, dtype=np.float64)


def _wal(factor: FloatArray) -> float:
    """Horizon-truncated WAL (years) from ``[F(0)=1, F(1), ..., F(H)]``: ``sum_{k<H} F(k)/12``."""
    return float(factor[:-1].sum() / 12.0)


def runoff_backtest(
    con: duckdb.DuckDBPyConnection,
    models: Mapping[str, Predictor],
    history: RatePath,
    t0: int,
    *,
    seal: Verifiable,
    cutoff_month: int,
    horizon: int = 24,
    replicates: int = 200,
    seed: int = 20261028,
) -> dict[str, Any]:
    """Observed vs projected pool run-off for the cohort active at ``t0``; needs a verified seal."""
    seal.verify()
    horizon = min(horizon, cutoff_month - t0)
    if horizon < 1:
        return {"t0": periods.to_iso(t0), "note": "no month after t0 before the cutoff"}
    loan_ids, statics = load_statics(con)
    data = load_runoff(con, t0, horizon, loan_ids, statics)
    if data.cohort.size == 0:
        return {"t0": periods.to_iso(t0), "note": "empty cohort"}
    mask = np.arange(1, horizon + 1)[None, :] <= data.observed_through[:, None]
    mask &= np.isfinite(data.observed[:, 1:])
    observed = observed_flows(data)
    observed_factor = _pool(data.observed[:, 1:], data.upb0, mask)
    b = contractual_path(data.upb0, data.rate, data.remaining0, horizon)
    hindsight = history.truncated(t0 + horizon - 1)
    as_of = history.truncated(t0).extended(
        np.full(horizon, history.truncated(t0).rate_30y[-1]),
        np.full(horizon, history.truncated(t0).rate_15y[-1]),
    )
    horizons = [h for h in REPORT_HORIZONS if h <= horizon]
    cumulative_observed = {
        name: _pool(np.nancumsum(values, axis=1), data.upb0, mask)
        for name, values in observed.items()
    }
    report: dict[str, Any] = {
        "t0": periods.to_iso(t0),
        "cohort_loans": data.cohort.size,
        "t0_balance_usd": float(data.upb0.sum()),
        "horizon_months": horizon,
        "censored_balance_share_by_horizon": float(data.upb0[~mask[:, -1]].sum() / data.upb0.sum()),
        "observation_gaps_loan_months": data.gaps,
        "observed": {
            "pool_factor": {f"{h}m": float(observed_factor[h - 1]) for h in horizons},
            "cumulative_principal_fraction": {
                name: {f"{h}m": float(series[h - 1]) for h in horizons}
                for name, series in cumulative_observed.items()
            },
            "wal_truncated_years": _wal(np.concatenate([[1.0], observed_factor])),
        },
        "models": {},
    }
    observed_interval = _bootstrap_factor(data, mask, horizon, replicates, seed)
    report["observed"]["pool_factor_interval_at_horizon"] = observed_interval
    for name, model in models.items():
        report["models"][name] = {}
        for mode, path in (("hindsight_rates", hindsight), ("as_of_flat_rates", as_of)):
            p = model_hazards(model, statics, data.cohort.loan_index, t0, path, horizon)
            alive_before = survival_before(statics, data.cohort.loan_index, t0, p)
            projected = projected_flows(p, alive_before, b)
            factor = _pool(projected["balance"], data.upb0, mask)
            cumulative = {
                part: _pool(np.cumsum(projected[part], axis=1), data.upb0, mask)
                for part in ("payoff", "credit_exit", "amortization")
            }
            report["models"][name][mode] = {
                "pool_factor": {f"{h}m": float(factor[h - 1]) for h in horizons},
                "pool_factor_error_pp": {
                    f"{h}m": float((factor[h - 1] - observed_factor[h - 1]) * 100) for h in horizons
                },
                "cumulative_principal_fraction": {
                    part: {f"{h}m": float(series[h - 1]) for h in horizons}
                    for part, series in cumulative.items()
                },
                "wal_truncated_years": _wal(np.concatenate([[1.0], factor])),
                "wal_error_years": _wal(np.concatenate([[1.0], factor]))
                - _wal(np.concatenate([[1.0], observed_factor])),
            }
    report["definitions"] = {
        "pool_factor": "sum of balances of loans still observed in month k / their t0 balance",
        "wal_truncated_years": "(1/12) * sum_{k=0}^{H-1} pool_factor(k), pool_factor(0) = 1",
        "cumulative_principal_fraction": "principal by component through month k / t0 balance, "
        "over loans still observed in k; observed amortization includes curtailments",
        "curtailment": "observed amortization minus contractual scheduled principal of "
        "continuing loans (not modeled by the engine)",
        "censoring": "censored loans leave both sides from the first unobserved month",
    }
    return report


def _bootstrap_factor(
    data: RunoffData, mask: np.ndarray, horizon: int, replicates: int, seed: int
) -> dict[str, float | str]:
    numerator = np.where(mask[:, -1], data.observed[:, horizon], 0.0)
    denominator = np.where(mask[:, -1], data.upb0, 0.0)
    rng = np.random.Generator(np.random.PCG64(seed))
    n = numerator.shape[0]
    draws = np.empty(replicates)
    for r in range(replicates):
        pick = rng.integers(0, n, size=n)
        draws[r] = numerator[pick].sum() / denominator[pick].sum()
    return {
        "low": float(np.quantile(draws, 0.025)),
        "high": float(np.quantile(draws, 0.975)),
        "kind": "loan_bootstrap_95",
    }
