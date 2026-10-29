"""Aalen-Johansen cumulative incidence against hand-computed examples and invariants."""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from prepay.evaluation.cohort import CENSORED, EVENT_C, EVENT_O, EVENT_P, aalen_johansen


def test_without_censoring_equals_empirical_incidence() -> None:
    last = np.array([1, 2, 2, 3, 4, 4, 4, 4])
    event = np.array([EVENT_P, EVENT_P, EVENT_C, EVENT_P, CENSORED, CENSORED, CENSORED, CENSORED])
    # Loans censored at the horizon (k=4) never left the risk set early: no censoring effect.
    curves = aalen_johansen(last, event, 4)
    np.testing.assert_allclose(curves["prepay"], [1 / 8, 2 / 8, 3 / 8, 3 / 8])
    np.testing.assert_allclose(curves["credit"], [0, 1 / 8, 1 / 8, 1 / 8])
    np.testing.assert_allclose(curves["survival"], [7 / 8, 5 / 8, 4 / 8, 4 / 8])


def test_censoring_reweights_later_events_by_hand() -> None:
    # 4 loans: one censored after month 1, then a payoff in month 2 among the 3 remaining.
    last = np.array([1, 2, 3, 3])
    event = np.array([CENSORED, EVENT_P, CENSORED, CENSORED])
    curves = aalen_johansen(last, event, 3)
    assert curves["at_risk"].tolist() == [4.0, 3.0, 2.0]
    np.testing.assert_allclose(curves["prepay"], [0.0, 1 / 3, 1 / 3])
    raw = (event == EVENT_P).mean()
    assert curves["prepay"][-1] > raw  # censoring correction raises incidence above 1/4


@given(
    st.lists(
        st.tuples(st.integers(0, 12), st.sampled_from([EVENT_P, EVENT_C, EVENT_O, CENSORED])),
        min_size=1,
        max_size=60,
    )
)
def test_incidence_and_survival_partition_probability(rows: list[tuple[int, int]]) -> None:
    last = np.array([r[0] for r in rows])
    event = np.array([r[1] if r[0] > 0 else CENSORED for r in rows])
    curves = aalen_johansen(last, event, 12)
    total = curves["prepay"] + curves["credit"] + curves["other"] + curves["survival"]
    np.testing.assert_allclose(total, 1.0, atol=1e-12)
    for name in ("prepay", "credit", "other"):
        assert np.all(np.diff(curves[name]) >= -1e-15)
        assert np.all((curves[name] >= 0) & (curves[name] <= 1))


def test_empty_risk_set_keeps_curves_flat() -> None:
    curves = aalen_johansen(np.array([1]), np.array([EVENT_P]), 3)
    assert curves["prepay"].tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert curves["at_risk"].tolist() == [1.0, 0.0, 0.0]


def test_build_cohort_truncates_outcomes_at_the_horizon_in_sql() -> None:
    import duckdb

    from prepay.evaluation.cohort import build_cohort

    t0, horizon = 100, 3
    con = duckdb.connect()
    con.execute(
        "create table int_loan_month_state (loan_id varchar, period_month integer, "
        "zero_balance_code varchar, current_upb double, modification_flag varchar)"
    )
    con.execute(
        "create table int_exit_events (loan_id varchar, event_type varchar, event_month int)"
    )
    events = {
        "a": ("prepay", t0 + 2),  # payoff inside the horizon
        "b": ("prepay", t0 + 5),  # payoff after the horizon -> censored at the horizon
        "c": ("credit", t0 + 3),  # credit exit in the last month
        "d": ("censor_modification", t0 + 3),  # censored before its month
        "e": ("censor_modification", t0 + 4),  # after the horizon -> censored at the horizon
        "f": ("censor_administrative", t0 + 2),  # observed through its month
    }
    for loan_id, (event_type, month) in events.items():
        con.execute(
            "insert into int_loan_month_state values (?, ?, null, 1000.0, '')", [loan_id, t0]
        )
        con.execute("insert into int_exit_events values (?, ?, ?)", [loan_id, event_type, month])
    cohort = build_cohort(con, t0, horizon, np.array(sorted(events), dtype=object))
    timing = zip(cohort.last_month.tolist(), cohort.event.tolist(), strict=True)
    got = dict(zip(cohort.loan_index.tolist(), timing, strict=True))
    assert got == {
        0: (2, EVENT_P),
        1: (3, CENSORED),
        2: (3, EVENT_C),
        3: (2, CENSORED),
        4: (3, CENSORED),
        5: (2, CENSORED),
    }
