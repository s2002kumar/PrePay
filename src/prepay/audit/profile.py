"""Aggregate data profile of a built warehouse (ADR 0006 §6): volumes, quality, missingness,
chronology and, through an outcome cutoff only, event distributions.

Every query returns counts, shares or summary statistics over many loans. No identifiers or rows
are emitted. Outcome distributions (events, terminal codes, losses) stop at ``outcomes_through``,
so post-validation outcomes stay unseen until the sealed lockbox opens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from prepay import periods
from prepay.ingest.lock import DataLock
from prepay.transform import warehouse_path

ORIGINATION_FIELDS = (
    "credit_score",
    "original_ltv",
    "original_cltv",
    "original_dti",
    "mi_pct",
    "number_of_units",
    "number_of_borrowers",
    "loan_purpose",
    "occupancy_status",
    "channel",
    "first_time_homebuyer",
    "property_type",
    "property_state",
)
PERFORMANCE_FIELDS = (
    "current_upb",
    "current_rate_pct",
    "remaining_months",
    "loan_age",
    "delinquency_status",
    "modification_flag",
)


def _rows(con: duckdb.DuckDBPyConnection, sql: str, **params: Any) -> list[dict[str, Any]]:
    relation = con.sql(sql, params=params or None)
    names = relation.columns
    return [dict(zip(names, row, strict=True)) for row in relation.fetchall()]


def _one(con: duckdb.DuckDBPyConnection, sql: str, **params: Any) -> dict[str, Any]:
    rows = _rows(con, sql, **params)
    return rows[0]


def profile(
    data_root: Path, lock: DataLock, *, outcomes_through: str = "2019-12"
) -> dict[str, Any]:
    through = periods.parse_iso(outcomes_through)
    bronze = (data_root / "bronze" / "sflld").as_posix()
    orig = f"read_parquet('{bronze}/*/*/origination.parquet', hive_partitioning=false)"
    perf = f"read_parquet('{bronze}/*/*/performance.parquet', hive_partitioning=false)"
    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
        report: dict[str, Any] = {
            "kind": "prepay-data-profile",
            "synthetic": lock.synthetic,
            "release": lock.release,
            "outcomes_through": outcomes_through,
        }
        report["volumes"] = {
            "bronze_origination": _one(
                con,
                f"select count(*) as rows, count(distinct loan_id) as loans from {orig}",  # noqa: S608
            ),
            "bronze_performance": _one(
                con,
                f"select count(*) as rows, count(distinct loan_id) as loans from {perf}",  # noqa: S608
            ),
            "loan_month_state": _one(
                con,
                "select count(*) as rows, count(distinct loan_id) as loans "
                "from int_loan_month_state",
            ),
            "eligible_loans": _one(con, "select count(*) as loans from int_loans")["loans"],
            "hazard_panel_by_window": _rows(
                con,
                """
                select case
                    when target_month <= $train then 'train'
                    when target_month <= $val_a then 'validation_a'
                    when target_month <= $val_b then 'validation_b'
                    else 'test (all windows)' end as window,
                    count(*) as rows, count(distinct loan_id) as loans
                from fct_hazard_panel group by 1 order by 1
                """,
                train=periods.month(2017, 12),
                val_a=periods.month(2018, 12),
                val_b=periods.month(2019, 12),
            ),
        }
        report["quality_findings"] = {
            r["finding"]: r["loans"]
            for r in _rows(con, "select finding, loans from agg_data_quality order by finding")
        }
        report["missingness_origination"] = _one(
            con,
            "select count(*) as loans, "  # noqa: S608 - fixed field names
            + ", ".join(f"avg(({f} is null)::int) as {f}" for f in ORIGINATION_FIELDS)
            + " from int_loans",
        )
        report["missingness_performance"] = _one(
            con,
            "select count(*) as rows, "  # noqa: S608 - fixed field names
            + ", ".join(f"avg(({f} is null)::int) as {f}" for f in PERFORMANCE_FIELDS)
            + " from int_loan_month_state",
        )
        report["chronology"] = _one(
            con,
            """
            select
                count(*) filter (where s.period_month < l.first_payment_month)
                    as rows_before_first_payment,
                count(distinct s.loan_id) filter (where s.period_month < l.first_payment_month)
                    as loans_with_rows_before_first_payment,
                count(*) filter (where s.period_month > l.maturity_month) as rows_after_maturity
            from int_loan_month_state as s
            inner join int_loans as l on s.loan_id = l.loan_id
            """,
        )
        report["first_payment_year_minus_archive_vintage"] = _rows(
            con,
            f"""
            select
                least(greatest(cast(substr(first_payment_date, 1, 4) as integer)
                    - cast(substr(_source_file, 13, 4) as integer), -1), 3) as years_after,
                count(*) as loans
            from {orig}
            where first_payment_date <> ''
            group by 1 order by 1
            """,  # noqa: S608
        )
        report["upb_disclosure_by_age"] = _rows(
            con,
            """
            select
                case when loan_age between 1 and 6 then '1-6'
                     when loan_age between 7 and 12 then '7-12'
                     else '13+' end as loan_age,
                count(*) as rows,
                avg((current_upb % 1000 = 0)::int) as share_multiple_of_1000
            from int_loan_month_state
            where current_upb > 0 and loan_age >= 1 and period_month <= $through
            group by 1 order by 1
            """,
            through=through,
        )
        report["events_through_cutoff"] = {
            "by_type": {
                r["event_type"]: r["loans"]
                for r in _rows(
                    con,
                    "select event_type, count(*) as loans from int_exit_events "
                    "where event_month <= $through group by 1 order by 1",
                    through=through,
                )
            },
            "by_year": _rows(
                con,
                """
                select event_month // 12 as year,
                    count(*) filter (where event_type = 'prepay') as prepay,
                    count(*) filter (where event_type = 'credit') as credit,
                    count(*) filter (where event_type like 'censor_%'
                        and event_type <> 'censor_administrative') as censored
                from int_exit_events where event_month <= $through
                group by 1 order by 1
                """,
                through=through,
            ),
            "terminal_codes": {
                r["code"]: r["loans"]
                for r in _rows(
                    con,
                    "select coalesce(terminal_code, 'none') as code, count(*) as loans "
                    "from int_exit_events where terminal_month <= $through group by 1 order by 1",
                    through=through,
                )
            },
        }
        report["credit_loss_fields_through_cutoff"] = _one(
            con,
            """
            select
                count(*) as credit_dispositions,
                count(*) filter (where s.actual_loss is not null) as with_actual_loss,
                avg(s.actual_loss / nullif(e.removal_upb, 0))
                    filter (where s.actual_loss is not null) as mean_loss_to_removal_upb,
                median(s.actual_loss / nullif(e.removal_upb, 0))
                    filter (where s.actual_loss is not null) as median_loss_to_removal_upb
            from int_exit_events as e
            inner join int_loan_month_state as s
                on s.loan_id = e.loan_id and s.period_month = e.terminal_month
            where e.event_type = 'credit' and e.event_month <= $through
            """,
            through=through,
        )
    return report
