"""Run-off comparison: projected balances reconcile with the finance engine; flows conserve."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np

from prepay.evaluation.cohort import CENSORED, EVENT_C, EVENT_O, EVENT_P, Cohort, survival_before
from prepay.evaluation.runoff import (
    RunoffData,
    _wal,
    contractual_path,
    observed_flows,
    projected_flows,
)
from prepay.finance.amortization import contractual_month
from prepay.finance.ledger import CreditAssumptions, HazardPaths, LoanLines, project

T0 = 2019 * 12 + 11


def _hazards(n: int, horizon: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    prepay = rng.uniform(0.0, 0.06, (n, horizon))
    credit = rng.uniform(0.0, 0.004, (n, horizon))
    return np.stack([1.0 - prepay - credit, prepay, credit], axis=2)


def test_projected_balance_equals_the_engine_ledger() -> None:
    # Independent check: the engine (schedule-before-exit) and the run-off decomposition
    # (exit at the start-of-month balance) must agree on the expected balance every month.
    rng = np.random.default_rng(7)
    n, horizon = 60, 24
    upb0 = rng.uniform(5e4, 6e5, n)
    rate = rng.uniform(0.0, 0.09, n)
    remaining0 = rng.integers(25, 360, n)
    remaining0[:6] = [1, 3, 8, 12, 20, 24]  # some loans mature inside the horizon
    p = _hazards(n, horizon, 8)
    statics: Any = SimpleNamespace(maturity_month=T0 + remaining0)
    alive_before = survival_before(statics, np.arange(n), T0, p)
    b = contractual_path(upb0, rate, remaining0, horizon)
    flows = projected_flows(p, alive_before, b)

    ledger = project(
        LoanLines(upb0, rate, remaining0),
        HazardPaths(prepay=p[:, :, 1], credit=p[:, :, 2], active=p[:, :, 0]),
        CreditAssumptions(severity=0.35, recovery_lag_months=6),
        horizon,
    ).pool
    np.testing.assert_allclose(flows["balance"].sum(axis=0), ledger.ending_upb, rtol=1e-10)
    # Each month's components account for the whole change in expected balance.
    start = np.concatenate([upb0[:, None], flows["balance"][:, :-1]], axis=1)
    np.testing.assert_allclose(
        flows["payoff"] + flows["credit_exit"] + flows["amortization"],
        start - flows["balance"],
        rtol=1e-10,
        atol=1e-6,
    )
    # Total principal leaving the pool matches the engine's three principal channels.
    np.testing.assert_allclose(
        (flows["payoff"] + flows["credit_exit"] + flows["amortization"]).sum(),
        (
            ledger.scheduled_principal
            + ledger.voluntary_prepay_principal
            + ledger.credit_exit_principal
        ).sum(),
        rtol=1e-10,
    )


def _data() -> RunoffData:
    """Five hand-built loans over a 4-month horizon with every outcome kind."""
    rate = np.full(5, 0.06)
    remaining0 = np.array([300, 300, 300, 2, 300])
    upb0 = np.full(5, 100_000.0)
    b = contractual_path(upb0, rate, remaining0, 4)
    observed = b.copy()
    observed[0, 2:] -= 5_000.0  # a 5,000 curtailment in month 2; continues to the horizon
    observed[1, 3:] = 0.0  # pays off in month 3
    observed[2, 2:] = 0.0  # credit exit in month 2
    observed[3, 2:] = 0.0  # matures in month 2 (two payments remaining at t0)
    observed[4, 2:] = np.nan  # censored: not observed from month 2
    cohort = Cohort(
        T0,
        np.arange(5),
        np.array([4, 3, 2, 2, 1]),
        np.array([CENSORED, EVENT_P, EVENT_C, EVENT_O, CENSORED]),
    )
    return RunoffData(
        cohort=cohort,
        upb0=upb0,
        rate=rate,
        remaining0=remaining0,
        observed=observed,
        exit_month=np.array([0, 3, 2, 2, 0]),
        exit_kind=np.array([CENSORED, EVENT_P, EVENT_C, EVENT_O, CENSORED]),
        observed_through=np.array([4, 4, 4, 4, 1]),
        gaps=0,
    )


def test_observed_components_conserve_balance_and_isolate_curtailment() -> None:
    data = _data()
    flows = observed_flows(data)
    o = data.observed
    total = flows["payoff"] + flows["credit_exit"] + flows["amortization"]
    in_u = np.isfinite(o[:, 1:])
    np.testing.assert_allclose(total[in_u], (o[:, :-1] - o[:, 1:])[in_u])
    assert flows["payoff"][1, 2] == o[1, 2]
    assert np.nansum(flows["payoff"]) == o[1, 2]
    assert flows["credit_exit"][2, 1] == o[2, 1]
    assert np.nansum(flows["credit_exit"]) == o[2, 1]
    assert flows["amortization"][3, 1] == o[3, 1]  # the final payment of a maturing loan
    assert np.isnan(flows["amortization"][4, 1:]).all()  # censored loan leaves the comparison
    _, scheduled = contractual_month(np.array([o[0, 1]]), np.array([0.06]), np.array([299]))
    np.testing.assert_allclose(flows["curtailment"][0, 1], o[0, 1] - o[0, 2] - scheduled[0])
    np.testing.assert_allclose(flows["curtailment"][0, 1], 5_000.0, rtol=1e-12)
    np.testing.assert_allclose(flows["curtailment"][0, 0], 0.0, atol=1e-6)
    np.testing.assert_allclose(flows["curtailment"][1:4, :].sum(), 0.0, atol=1e-6)


def test_truncated_wal_counts_each_month_outstanding() -> None:
    assert _wal(np.ones(25)) == 2.0  # nothing repaid over 24 months: 24 months outstanding
    assert _wal(np.concatenate([[1.0], np.zeros(24)])) == 1.0 / 12.0
