"""Full-scale audits (ADR 0006 §6): agreement counts only, and they detect real disagreement."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import duckdb

from prepay.audit.agreement import run_audit
from prepay.audit.profile import profile
from prepay.contracts.sflld import LOAN_ID_PATTERN
from prepay.ingest.lock import DataLock
from prepay.transform import warehouse_path


def _no_loan_ids(report: dict) -> None:
    assert re.search(LOAN_ID_PATTERN, json.dumps(report)) is None


def test_audit_covers_every_loan_and_agrees(built: tuple[Path, DataLock]) -> None:
    root, lock = built
    report = run_audit(root, lock, slices=2, slice_buckets=5_000)  # two halves = all loans
    assert report["loan_share_audited"] == 1.0
    assert report["labels_all_agree"] is True
    assert report["features"]["all_match"] is True
    totals = report["labels"]["totals"]
    assert totals["panel_outcomes"]["agree"] > 10_000
    assert totals["quarantined"]["agree"] > 0  # the tiny dataset injects anomalies
    _no_loan_ids(report)


def test_audit_reports_a_planted_label_disagreement(
    built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    copy = tmp_path / "copy"
    shutil.copytree(root / "bronze", copy / "bronze")
    warehouse_path(copy).parent.mkdir(parents=True)
    shutil.copy(warehouse_path(root), warehouse_path(copy))
    with duckdb.connect(str(warehouse_path(copy))) as con:
        con.execute(
            "update int_exit_events set event_type = 'credit' where loan_id = "
            "(select loan_id from int_exit_events where event_type = 'prepay' limit 1)"
        )
    report = run_audit(copy, lock, slices=2, slice_buckets=5_000)
    assert report["labels_all_agree"] is False
    mismatches = report["labels"]["totals"]["first_events"]["value_mismatch"]
    assert mismatches == 1
    kinds = [s["first_events"]["value_mismatch_by_kind"] for s in report["labels"]["slices"]]
    assert {"prepay -> credit": 1} in kinds


def test_profile_is_aggregate_and_respects_the_outcome_cutoff(
    built: tuple[Path, DataLock],
) -> None:
    root, lock = built
    report = profile(root, lock, outcomes_through="2019-12")
    volumes = report["volumes"]
    assert volumes["bronze_origination"]["loans"] >= volumes["eligible_loans"] > 0
    assert sum(w["rows"] for w in volumes["hazard_panel_by_window"]) > 10_000
    years = [row["year"] for row in report["events_through_cutoff"]["by_year"]]
    assert max(years) <= 2019
    assert report["quality_findings"]["is_quarantined"] > 0
    assert 0.0 <= report["missingness_origination"]["credit_score"] <= 1.0
    _no_loan_ids(report)


def test_fingerprint_is_stable_and_detects_one_changed_value(
    built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    from prepay.audit.fingerprint import warehouse_fingerprint

    root, _ = built
    first = warehouse_fingerprint(root)
    assert first == warehouse_fingerprint(root)
    copy = tmp_path / "copy"
    warehouse_path(copy).parent.mkdir(parents=True)
    shutil.copy(warehouse_path(root), warehouse_path(copy))
    with duckdb.connect(str(warehouse_path(copy))) as con:
        con.execute(
            "update fct_hazard_panel set exposure_upb = exposure_upb + 0.01 "
            "where rowid = (select min(rowid) from fct_hazard_panel)"
        )
    changed = warehouse_fingerprint(copy)
    assert {t for t in first if first[t] != changed[t]} == {"fct_hazard_panel"}
    assert changed["fct_hazard_panel"]["rows"] == first["fct_hazard_panel"]["rows"]
