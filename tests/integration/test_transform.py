"""dbt silver/gold layer against independent references: a Python decision-table oracle, the
synthetic generator's ground truth, and deliberately corrupted copies that the guards must catch.
"""

from __future__ import annotations

import collections
import json
import shutil
from pathlib import Path

import duckdb
import numpy as np
import pytest

from prepay import periods
from prepay.contracts import dbt_codegen
from prepay.ingest.lock import DataLock
from prepay.synthetic import truth
from prepay.transform import TransformError, run_dbt, warehouse_path
from tests.integration import label_oracle

ANOMALY_FINDING = {
    "orphan_performance": "orphan_performance",
    "duplicate_exact_period": "exact_duplicate_period",
    "duplicate_conflicting_period": "conflicting_duplicate_period",
    "missing_period_gap": "period_gap",
    "invalid_zero_balance_code": "field_domain_violation",
    "rows_after_termination": "rows_after_termination",
    "modification_with_terminal_same_month": "modification_with_terminal_same_month",
    "missing_zero_balance_effective_date": "missing_zero_balance_effective_date",
    "duplicate_origination": "duplicate_origination",
}


def query(root: Path, sql: str) -> list[tuple]:
    with duckdb.connect(str(warehouse_path(root)), read_only=True) as con:
        return con.sql(sql).fetchall()


def test_generated_contract_macros_are_current() -> None:
    committed = dbt_codegen.TARGET.read_text(encoding="utf-8")
    assert committed == dbt_codegen.render(), "run: uv run python -m prepay.contracts.dbt_codegen"


def test_quarantine_flags_exactly_the_injected_anomalies(
    built: tuple[Path, DataLock], tiny_dataset: Path
) -> None:
    root, _ = built
    manifest = json.loads((tiny_dataset / "manifest.json").read_text(encoding="utf-8"))
    expected = collections.defaultdict(set)
    for vintage in manifest["vintages"]:
        for anomaly in vintage["anomalies"]:
            expected[ANOMALY_FINDING[anomaly["kind"]]].add(anomaly["loan_id"])
    for finding, loans in expected.items():
        found = {r[0] for r in query(root, f"select loan_id from int_loan_quality where {finding}")}
        assert found == loans, finding
    quarantined = {
        r[0] for r in query(root, "select loan_id from int_loan_quality where is_quarantined")
    }
    assert quarantined == set().union(
        *(v for k, v in expected.items() if k != "exact_duplicate_period")
    )


def test_sql_labels_match_independent_python_oracle(built: tuple[Path, DataLock]) -> None:
    root, lock = built
    oracle = label_oracle.run(root / "bronze", periods.parse_iso(lock.performance_cutoff_month))
    sql_quarantined = {
        r[0] for r in query(root, "select loan_id from int_loan_quality where is_quarantined")
    }
    sql_excluded = {
        r[0]
        for r in query(
            root, "select loan_id from int_loan_quality where is_excluded and not is_quarantined"
        )
    }
    assert sql_quarantined == oracle.quarantined
    assert sql_excluded == oracle.excluded
    sql_events = {
        r[0]: (r[1], r[2])
        for r in query(root, "select loan_id, event_type, event_month from int_exit_events")
    }
    assert sql_events == oracle.events
    sql_panel = {
        (r[0], r[1]): r[2]
        for r in query(root, "select loan_id, target_month, outcome from fct_hazard_panel")
    }
    assert sql_panel == oracle.panel
    counts = collections.Counter(sql_panel.values())
    assert counts["P"] > 100
    assert counts["C"] > 5


def test_labels_agree_with_generator_truth(
    built: tuple[Path, DataLock], tiny_dataset: Path
) -> None:
    root, _ = built
    con = duckdb.connect()
    truth_rows = con.sql(
        f"select loan_id, period, outcome from "
        f"read_parquet('{(tiny_dataset / 'truth').as_posix()}/*.parquet')"
    ).fetchall()
    truth_outcome = {(lid, periods.parse_yyyymm(str(per))): int(o) for lid, per, o in truth_rows}
    panel = query(root, "select loan_id, target_month, outcome from fct_hazard_panel")
    expected = {"A": 0, "P": 1, "C": 2}
    for loan_id, month, outcome in panel:
        assert truth_outcome[(loan_id, month)] == expected[outcome], (loan_id, month)


def test_gold_features_reproduce_true_hazards(
    built: tuple[Path, DataLock], tiny_dataset: Path
) -> None:
    """Recompute the generator's true probabilities from gold features: any as-of slip in rates,
    burnout, age or calendar alignment would change them."""
    root, _ = built
    rows = query(
        root,
        "select loan_id, target_month, incentive_bps, loan_age, burnout_months, credit_score, "
        "original_ltv, original_dti, exp(log_original_upb) from fct_hazard_panel "
        "order by loan_id, target_month",
    )
    con = duckdb.connect()
    true = {
        (lid, periods.parse_yyyymm(str(per))): (p, c)
        for lid, per, p, c in con.sql(
            f"select loan_id, period, true_prepay, true_credit from "
            f"read_parquet('{(tiny_dataset / 'truth').as_posix()}/*.parquet')"
        ).fetchall()
    }
    by_month = collections.defaultdict(list)
    for row in rows:
        by_month[row[1]].append(row)
    worst = 0.0
    for month, group in by_month.items():

        def column(i: int, group: list = group) -> np.ndarray:
            return np.array([np.nan if r[i] is None else r[i] for r in group], dtype=float)

        state = truth.LoanState(
            incentive_bps=column(2),
            age_months=column(3).astype(np.int64),
            burnout_months=column(4).astype(np.int64),
            calendar_month=month,
            fico=column(5),
            ltv=column(6),
            dti=column(7),
            original_upb=column(8),
        )
        p, c, _ = truth.outcome_probabilities(state)
        expected = np.array([true[(r[0], month)] for r in group])
        worst = max(
            worst,
            float(np.max(np.abs(p - expected[:, 0]))),
            float(np.max(np.abs(c - expected[:, 1]))),
        )
    assert worst < 1e-9, worst


def test_features_are_point_in_time(built: tuple[Path, DataLock]) -> None:
    root, _ = built
    leaks = query(
        root,
        """
        select count(*) from fct_hazard_panel
        where rate_observed_t1 > (make_date(cast((target_month - 1) // 12 as integer),
                                            cast((target_month - 1) % 12 + 1 as integer), 1)
                                  + interval 1 month - interval 1 day)::date""",
    )
    assert leaks == [(0,)]


def _corrupted_copy(root: Path, tmp_path: Path, statement: str) -> Path:
    copy = tmp_path / "corrupt"
    shutil.copytree(root / "bronze", copy / "bronze")
    warehouse_path(copy).parent.mkdir(parents=True)
    shutil.copy(warehouse_path(root), warehouse_path(copy))
    with duckdb.connect(str(warehouse_path(copy))) as con:
        con.execute(statement)
    return copy


@pytest.mark.parametrize(
    "statement",
    [
        # look-ahead: a feature rate observed after the end of t-1
        "update fct_hazard_panel set rate_observed_t1 = rate_observed_t1 + 40 "
        "where target_month = (select max(target_month) from fct_hazard_panel)",
        # a labelled month after the loan's first event
        "insert into fct_hazard_panel by name (select * replace (target_month + 1 as target_month) "
        "from fct_hazard_panel where outcome = 'P' limit 1)",
    ],
    ids=["look_ahead_rate", "row_after_event"],
)
def test_guards_fail_on_corrupted_gold(
    built: tuple[Path, DataLock], tmp_path: Path, statement: str
) -> None:
    root, lock = built
    copy = _corrupted_copy(root, tmp_path, statement)
    with pytest.raises(TransformError, match="test"):
        run_dbt(copy, lock, command="test")


def test_transform_requires_ingested_bronze(tmp_path: Path, built: tuple[Path, DataLock]) -> None:
    with pytest.raises(TransformError, match="prepay ingest"):
        run_dbt(tmp_path, built[1])
