"""Censor-aware cohort run-off backtest (MODELING §7-§8, SPEC gate P7).

A cohort is every eligible loan observed active at the end of ``t0``. Realized cumulative
incidence of voluntary payoff (P) and credit disposition (C) over the next ``H`` months is
estimated with the discrete-time **Aalen-Johansen** estimator:

- modification, whole-loan sale, RPL securitization and defect **censor** the loan *before* the
  month in which they are reported (that month's outcome is unobserved);
- an administrative or unexplained end censors *after* its last (active) month;
- maturity is a competing exit, not a payoff.

Model-implied incidence averages each loan's ``sum_k S(k-1) p_P(k)``, using hazards from features
built only from loan attributes and a rate path. **Hindsight** mode uses the realized month-end
rates and isolates behavioral error. **As-of** mode holds the rates known at ``t0`` flat and is a
genuine forecast. The model never sees which loans are later censored. Censoring by modification
is informative (ADR 0003), so the AJ curve estimates incidence under that caveat.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import duckdb
import numpy as np

from prepay import periods
from prepay.arrays import FloatArray, IntArray
from prepay.features.batch import PanelBatch
from prepay.features.machine import LoanStatics, RatePath, compute_features
from prepay.features.panel import load_statics

CENSOR_BEFORE = (
    "censor_modification",
    "censor_whole_loan_sale",
    "censor_reperforming_securitization",
    "censor_defect",
)
CENSOR_AFTER = ("censor_administrative", "censor_unexplained_end")
EVENT_P, EVENT_C, EVENT_O, CENSORED = 1, 2, 3, 0


class Predictor(Protocol):
    def predict_proba(self, batch: PanelBatch) -> FloatArray: ...


class Verifiable(Protocol):
    def verify(self) -> None: ...


@dataclass(frozen=True)
class Cohort:
    t0: int
    loan_index: IntArray  # into the statics returned by load_statics
    last_month: IntArray  # last month index k (1-based after t0) the loan is at risk
    event: IntArray  # EVENT_P / EVENT_C / EVENT_O, or CENSORED

    @property
    def size(self) -> int:
        return int(self.loan_index.shape[0])


def build_cohort(
    con: duckdb.DuckDBPyConnection, t0: int, horizon: int, loan_ids: np.ndarray
) -> Cohort:
    """Eligible loans active at the end of ``t0`` and their realized timing within the horizon.

    Outcomes after ``t0 + horizon`` are collapsed in SQL, so they are never fetched.
    """
    rows = con.execute(
        """
        select
            s.loan_id,
            case when e.event_month > $end then 'beyond_horizon' else e.event_type end,
            least(e.event_month, $end + 1)
        from int_loan_month_state as s
        inner join int_exit_events as e on s.loan_id = e.loan_id
        where s.period_month = $t0
          and s.zero_balance_code is null
          and s.current_upb > 0
          and coalesce(s.modification_flag, '') = ''
          and e.event_month > $t0
        order by s.loan_id
        """,
        {"t0": t0, "end": t0 + horizon},
    ).fetchall()
    position = {lid: i for i, lid in enumerate(loan_ids)}
    index, last, event = [], [], []
    for loan_id, event_type, event_month in rows:
        k = int(event_month) - t0
        if k > horizon:
            last.append(horizon)
            event.append(CENSORED)
        elif event_type == "prepay":
            last.append(k)
            event.append(EVENT_P)
        elif event_type == "credit":
            last.append(k)
            event.append(EVENT_C)
        elif event_type == "maturity":
            last.append(k)
            event.append(EVENT_O)
        elif event_type in CENSOR_BEFORE:
            last.append(k - 1)
            event.append(CENSORED)
        elif event_type in CENSOR_AFTER:
            last.append(k)
            event.append(CENSORED)
        else:
            raise ValueError(f"unexpected event type {event_type}")
        index.append(position[loan_id])
    return Cohort(
        t0,
        np.array(index, dtype=np.int64),
        np.array(last, dtype=np.int64),
        np.array(event, dtype=np.int64),
    )


def aalen_johansen(last: IntArray, event: IntArray, horizon: int) -> dict[str, FloatArray]:
    """Discrete-time cumulative incidence of P, C and other exits, plus overall survival."""
    survival, cif = 1.0, {EVENT_P: 0.0, EVENT_C: 0.0, EVENT_O: 0.0}
    curves: dict[str, list[float]] = {
        "prepay": [],
        "credit": [],
        "other": [],
        "survival": [],
        "at_risk": [],
    }
    for k in range(1, horizon + 1):
        at_risk = int((last >= k).sum())
        exits = {e: int(((last == k) & (event == e)).sum()) for e in cif}
        if at_risk > 0:
            for e, d in exits.items():
                cif[e] += survival * d / at_risk
            survival *= 1.0 - sum(exits.values()) / at_risk
        curves["prepay"].append(cif[EVENT_P])
        curves["credit"].append(cif[EVENT_C])
        curves["other"].append(cif[EVENT_O])
        curves["survival"].append(survival)
        curves["at_risk"].append(float(at_risk))
    return {name: np.asarray(values) for name, values in curves.items()}


#: Loans whose features are built and scored together; bounds memory for large real cohorts.
CHUNK_LOANS = 20_000


def model_hazards(
    model: Predictor,
    statics: LoanStatics,
    loan_index: IntArray,
    t0: int,
    rates: RatePath,
    horizon: int,
    *,
    chunk_loans: int = CHUNK_LOANS,
) -> FloatArray:
    """Month ``t0+k`` class probabilities for each loan, ``(n, horizon, 3)``, scored in chunks."""
    n = int(loan_index.shape[0])
    out = np.empty((n, horizon, 3))
    months = np.arange(t0 + 1, t0 + horizon + 1)
    for start in range(0, n, chunk_loans):
        part = loan_index[start : start + chunk_loans]
        rows = np.repeat(part, horizon)
        target = np.tile(months, part.shape[0])
        batch = PanelBatch(
            loan_id=rows.astype(object),
            target_month=target,
            outcome_class=np.zeros(target.size, dtype=np.int64),
            exposure_upb=np.zeros(target.size),
            features=compute_features(statics, rates, rows, target),
            loan_code=rows,
        )
        p = np.asarray(model.predict_proba(batch))
        out[start : start + part.shape[0]] = p.reshape(part.shape[0], horizon, 3)
    return out


def survival_before(
    statics: LoanStatics, loan_index: IntArray, t0: int, p: FloatArray
) -> FloatArray:
    """``S(k-1)``: probability of being active at the start of month ``t0+k``, ``(n, horizon)``.

    The final contractual payment month ends the loan (maturity), whatever the hazards say.
    """
    n, horizon = p.shape[0], p.shape[1]
    maturity = statics.maturity_month[loan_index] - t0  # month k of final payment
    months = np.arange(1, horizon + 1)
    alive_before = np.ones((n, horizon))
    survive = np.where(months[None, :] < maturity[:, None], p[:, :, 0], 0.0)
    alive_before[:, 1:] = np.cumprod(survive, axis=1)[:, :-1]
    return alive_before


def model_incidence(
    model: Predictor, statics: LoanStatics, cohort: Cohort, rates: RatePath, horizon: int
) -> dict[str, FloatArray]:
    """Mean model-implied cumulative incidence over the cohort (count-weighted)."""
    p = model_hazards(model, statics, cohort.loan_index, cohort.t0, rates, horizon)
    alive_before = survival_before(statics, cohort.loan_index, cohort.t0, p)
    return {
        "prepay": (alive_before * p[:, :, 1]).cumsum(axis=1).mean(axis=0),
        "credit": (alive_before * p[:, :, 2]).cumsum(axis=1).mean(axis=0),
    }


def censoring_sensitivity(
    cohort: Cohort, horizon: int, statics: LoanStatics, history: RatePath
) -> dict[str, Any]:
    """ADR 0006 §10: payoff incidence bounds under extreme assumptions about censored loans.

    Lower bound: every loan censored inside the horizon stays active, without payoff, to the
    horizon. Upper bound: every such loan pays off in its censoring month. Also compares censored
    and other loans on characteristics known at ``t0``.
    """
    censored = (cohort.event == CENSORED) & (cohort.last_month < horizon)
    never_last = np.where(censored, horizon, cohort.last_month)
    all_last = np.where(censored, cohort.last_month + 1, cohort.last_month)
    all_event = np.where(censored, EVENT_P, cohort.event)
    estimate = aalen_johansen(cohort.last_month, cohort.event, horizon)["prepay"][-1]
    low = aalen_johansen(never_last, cohort.event, horizon)["prepay"][-1]
    high = aalen_johansen(all_last, all_event, horizon)["prepay"][-1]
    features = compute_features(
        statics, history, cohort.loan_index, np.full(cohort.size, cohort.t0 + 1)
    )

    def profile(mask: np.ndarray) -> dict[str, float | int | None]:
        def mean(name: str) -> float | None:
            values = np.asarray(features[name], dtype=np.float64)[mask]
            values = values[np.isfinite(values)]
            return float(values.mean()) if values.size else None

        return {
            "loans": int(mask.sum()),
            "mean_credit_score": mean("credit_score"),
            "mean_original_ltv": mean("original_ltv"),
            "mean_incentive_bps_at_t0": mean("incentive_bps"),
        }

    return {
        "horizon_months": horizon,
        "censored_share": float(censored.mean()),
        "prepay_incidence": {
            "aalen_johansen": float(estimate),
            "bound_censored_never_pay_off": float(low),
            "bound_censored_all_pay_off": float(high),
        },
        "censored_profile": profile(censored),
        "uncensored_profile": profile(~censored),
    }


def _bootstrap(cohort: Cohort, horizon: int, replicates: int, seed: int) -> FloatArray:
    rng = np.random.Generator(np.random.PCG64(seed))
    draws = np.empty((replicates, horizon))
    for b in range(replicates):
        pick = rng.integers(0, cohort.size, cohort.size)
        draws[b] = aalen_johansen(cohort.last_month[pick], cohort.event[pick], horizon)["prepay"]
    return draws


def backtest(
    con: duckdb.DuckDBPyConnection,
    models: Mapping[str, Predictor],
    history: RatePath,
    t0: int,
    horizons: tuple[int, ...] = (6, 12, 24),
    *,
    seal: Verifiable,
    cutoff_month: int,
    replicates: int = 200,
    seed: int = 20261028,
) -> dict[str, Any]:
    """Realized vs model cumulative payoff incidence for the cohort active at ``t0``.

    Reads realized post-``t0`` outcomes, so it requires a verified seal like any holdout access.
    """
    seal.verify()
    mature = tuple(h for h in horizons if t0 + h <= cutoff_month)
    if not mature:
        return {"t0": periods.to_iso(t0), "note": "no mature horizon before the cutoff"}
    horizon = max(mature)
    loan_ids, statics = load_statics(con)
    cohort = build_cohort(con, t0, horizon, loan_ids)
    if cohort.size == 0:
        return {"t0": periods.to_iso(t0), "note": "empty cohort"}
    realized = aalen_johansen(cohort.last_month, cohort.event, horizon)
    draws = _bootstrap(cohort, horizon, replicates, seed)
    raw_prepay = np.array(
        [
            ((cohort.event == EVENT_P) & (cohort.last_month <= k)).mean()
            for k in range(1, horizon + 1)
        ]
    )
    hindsight = history.truncated(t0 + horizon - 1)
    as_of = history.truncated(t0).extended(
        np.full(horizon, history.truncated(t0).rate_30y[-1]),
        np.full(horizon, history.truncated(t0).rate_15y[-1]),
    )
    modes = {"hindsight_rates": hindsight, "as_of_flat_rates": as_of}
    model_curves = {
        name: {
            mode: model_incidence(model, statics, cohort, path, horizon)
            for mode, path in modes.items()
        }
        for name, model in models.items()
    }
    by_horizon = {}
    for h in mature:
        k = h - 1
        entry: dict[str, Any] = {
            "realized_aalen_johansen_prepay": float(realized["prepay"][k]),
            "realized_prepay_interval": {
                "low": float(np.quantile(draws[:, k], 0.025)),
                "high": float(np.quantile(draws[:, k], 0.975)),
                "kind": "loan_bootstrap_95",
            },
            "realized_aalen_johansen_credit": float(realized["credit"][k]),
            "raw_observed_prepay_ignoring_censoring": float(raw_prepay[k]),
            "censored_share": float(((cohort.event == CENSORED) & (cohort.last_month < h)).mean()),
            "models": {},
        }
        for name, curves in model_curves.items():
            entry["models"][name] = {
                mode: {
                    "prepay": float(c["prepay"][k]),
                    "credit": float(c["credit"][k]),
                    "prepay_error_pp": float((c["prepay"][k] - realized["prepay"][k]) * 100),
                }
                for mode, c in curves.items()
            }
        by_horizon[f"{h}m"] = entry
    return {
        "t0": periods.to_iso(t0),
        "cohort_loans": cohort.size,
        "estimand": "count-weighted cumulative incidence of full voluntary payoff",
        "horizons": by_horizon,
        "censoring_sensitivity": censoring_sensitivity(cohort, horizon, statics, history),
    }
