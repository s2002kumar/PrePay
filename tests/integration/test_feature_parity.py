"""Historical vs scenario feature parity (MODELING §4, ARCHITECTURE §5).

The Python state machine, fed only static loan attributes and a rate path built from raw weekly
observations, must reproduce every gold-panel feature computed by dbt.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pytest

from prepay import periods
from prepay.features import CATEGORICAL, FEATURES, NUMERIC, compute_features
from prepay.features.machine import RatePath
from prepay.features.panel import (
    PanelBatch,
    load_statics,
    rate_path_from_bronze,
    read_panel,
    sample_clause,
)
from prepay.ingest.lock import DataLock
from prepay.transform import warehouse_path


@pytest.fixture(scope="module")
def gold(built: tuple[Path, DataLock]) -> tuple[Path, PanelBatch]:
    root, _ = built
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        batch = read_panel(con, 0, periods.month(2100, 1))
    return root, batch


def test_state_machine_reproduces_every_gold_feature(gold: tuple[Path, PanelBatch]) -> None:
    root, batch = gold
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        loan_ids, statics = load_statics(con)
    position = {lid: i for i, lid in enumerate(loan_ids)}
    loan_index = np.array([position[lid] for lid in batch.loan_id])
    rates = rate_path_from_bronze(root / "bronze")
    python = compute_features(statics, rates, loan_index, batch.target_month)
    assert set(python) == {f.name for f in FEATURES}
    for name in NUMERIC:
        np.testing.assert_allclose(
            python[name].astype(float),
            batch.features[name],
            rtol=1e-12,
            atol=1e-9,
            equal_nan=True,
            err_msg=name,
        )
    for name in CATEGORICAL:
        assert list(python[name]) == list(batch.features[name]), name
    assert batch.rows > 10_000


def test_python_as_of_rates_match_dbt_monthly_rates(built: tuple[Path, DataLock]) -> None:
    root, _ = built
    rates = rate_path_from_bronze(root / "bronze")
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        rows = con.execute(
            "select month, rate_30y, rate_15y, pmms_application_based from int_monthly_rates "
            "order by month"
        ).fetchall()
    months = np.array([r[0] for r in rows])
    assert months[0] == rates.first_month
    assert months[-1] == rates.last_month
    np.testing.assert_array_equal(rates.rate_30y, [r[1] for r in rows])
    np.testing.assert_array_equal(rates.rate_15y, [r[2] for r in rows])
    np.testing.assert_array_equal(rates.application_based, [r[3] for r in rows])


def test_scenario_extension_uses_hypothetical_rates_only_after_t0(
    built: tuple[Path, DataLock],
) -> None:
    root, _ = built
    history = rate_path_from_bronze(root / "bronze")
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        _, statics = load_statics(con)
    t0 = history.last_month
    horizon = 24
    shocked = history.extended(np.full(horizon, 3.0), np.full(horizon, 2.4))
    base = history.extended(
        np.full(horizon, history.rate_30y[-1]), np.full(horizon, history.rate_15y[-1])
    )
    rows = np.repeat(np.arange(5), horizon)
    months = np.tile(np.arange(t0 + 1, t0 + horizon + 1), 5)
    a = compute_features(statics, shocked, rows, months)
    b = compute_features(statics, base, rows, months)
    first = months == t0 + 1
    # Month t0+1 only uses rates through t0: identical under any scenario.
    np.testing.assert_array_equal(a["incentive_bps"][first], b["incentive_bps"][first])
    later = months == t0 + 2
    assert not np.array_equal(a["incentive_bps"][later], b["incentive_bps"][later])
    # Contract and origination features never depend on rates.
    np.testing.assert_array_equal(a["loan_age"], b["loan_age"])
    np.testing.assert_array_equal(a["note_rate_pct"], b["note_rate_pct"])
    assert shocked.hypothetical_from == t0 + 1
    with pytest.raises(ValueError, match="t-1"):
        compute_features(statics, history, np.array([0]), np.array([t0 + 2]))


def test_scenario_rates_must_be_finite() -> None:
    path = RatePath(0, np.ones(3), np.ones(3), np.zeros(3, dtype=bool))
    with pytest.raises(ValueError, match="finite"):
        path.extended(np.array([np.nan]), np.array([1.0]))
    with pytest.raises(ValueError, match="equal length"):
        path.extended(np.ones(2), np.ones(3))


def test_sampling_is_loan_consistent(built: tuple[Path, DataLock]) -> None:
    root, _ = built
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        full = read_panel(con, 0, periods.month(2100, 1))
        half = read_panel(con, 0, periods.month(2100, 1), sample_fraction=0.5)
        again = read_panel(con, 0, periods.month(2100, 1), sample_fraction=0.5)
    kept = set(half.loan_id)
    assert 0.35 < len(kept) / len(set(full.loan_id)) < 0.65
    full_rows = sum(1 for lid in full.loan_id if lid in kept)
    assert full_rows == half.rows  # whole loans kept, never partial paths
    assert list(half.loan_id) == list(again.loan_id)
    with pytest.raises(ValueError, match="sample_fraction"):
        sample_clause(1.5)
