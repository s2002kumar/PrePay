"""Generated synthetic datasets conform to the SFLLD contract, are deterministic, and contain
exactly the anomalies their manifest declares."""

from __future__ import annotations

import collections
import dataclasses
import io
import json
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pytest

from prepay import periods
from prepay.cli import main
from prepay.contracts.sflld import LOAN_ID_PATTERN, ORIGINATION, PERFORMANCE
from prepay.synthetic.dataset import generate_dataset
from tests.conftest import TINY_CONFIG

Row = list[str]


def manifest(root: Path) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def read_members(root: Path, vintage: int) -> tuple[list[Row], list[Row]]:
    with zipfile.ZipFile(root / "raw" / "sflld" / f"sample_{vintage}.zip") as archive:
        assert archive.namelist() == [f"sample_orig_{vintage}.txt", f"sample_perf_{vintage}.txt"]
        tables = []
        for name in archive.namelist():
            text = io.TextIOWrapper(archive.open(name), encoding="utf-8")
            tables.append([line.rstrip("\n").split("|") for line in text])
    return tables[0], tables[1]


def anomalies_of(root: Path) -> list[dict]:
    return [a for v in manifest(root)["vintages"] for a in v["anomalies"]]


def test_manifest_describes_a_fictional_dataset(tiny_dataset: Path) -> None:
    m = manifest(tiny_dataset)
    assert m["synthetic"] is True
    assert "not Freddie Mac data" in m["notice"]
    assert m["layout"]["origination_fingerprint"] == ORIGINATION.fingerprint()
    assert m["layout"]["performance_fingerprint"] == PERFORMANCE.fingerprint()
    assert [v["vintage"] for v in m["vintages"]] == list(range(2006, 2027))
    assert m["totals"]["loans"] == sum(TINY_CONFIG.loans_in(v) for v in range(2006, 2027))


def test_every_value_conforms_except_declared_anomalies(tiny_dataset: Path) -> None:
    injected_codes = {
        (a["loan_id"], a["period"])
        for a in anomalies_of(tiny_dataset)
        if a["kind"] == "invalid_zero_balance_code"
    }
    found: set[tuple[str, str]] = set()
    for v in manifest(tiny_dataset)["vintages"]:
        orig, perf = read_members(tiny_dataset, v["vintage"])
        assert len(orig) == v["members"][0]["rows"]
        assert len(perf) == v["members"][1]["rows"]
        for layout, rows in ((ORIGINATION, orig), (PERFORMANCE, perf)):
            for row in rows:
                assert len(row) == layout.width
                for spec, raw in zip(layout.fields, row, strict=True):
                    problem = spec.violation(raw)
                    if problem is not None:
                        assert spec.name == "zero_balance_code", (spec.name, raw, problem)
                        found.add((row[0], row[1]))
    assert found == injected_codes


def test_generation_is_deterministic(tiny_dataset: Path, tmp_path: Path) -> None:
    again = generate_dataset(TINY_CONFIG, tmp_path / "again")
    first = manifest(tiny_dataset)
    for a, b in zip(first["vintages"], again["vintages"], strict=True):
        assert a["members"] == b["members"]
        assert a["truth"]["sha256"] == b["truth"]["sha256"]
    assert first["rates"] == again["rates"]
    other = generate_dataset(dataclasses.replace(TINY_CONFIG, seed=12), tmp_path / "other")
    assert other["vintages"][0]["members"] != first["vintages"][0]["members"]


def test_each_declared_anomaly_is_present(tiny_dataset: Path) -> None:
    declared = anomalies_of(tiny_dataset)
    kinds = collections.Counter(a["kind"] for a in declared)
    assert set(kinds) >= {
        "orphan_performance",
        "duplicate_exact_period",
        "missing_period_gap",
        "duplicate_origination",
        "rows_after_termination",
    }
    for v in manifest(tiny_dataset)["vintages"]:
        orig, perf = read_members(tiny_dataset, v["vintage"])
        orig_ids = collections.Counter(r[ORIGINATION.field("loan_id").position - 1] for r in orig)
        by_key = collections.defaultdict(list)
        by_loan = collections.defaultdict(list)
        for row in perf:
            by_key[(row[0], row[1])].append(row)
            by_loan[row[0]].append(row)
        for a in v["anomalies"]:
            lid, per, kind = a["loan_id"], a["period"], a["kind"]
            if kind == "orphan_performance":
                assert lid not in orig_ids
                assert len(by_loan[lid]) == 3
            elif kind == "duplicate_exact_period":
                rows = by_key[(lid, per)]
                assert len(rows) == 2
                assert rows[0] == rows[1]
            elif kind == "duplicate_conflicting_period":
                rows = by_key[(lid, per)]
                assert len(rows) == 2
                assert rows[0][2] != rows[1][2]
            elif kind == "missing_period_gap":
                assert not by_key[(lid, per)]
                months = [periods.parse_yyyymm(r[1]) for r in by_loan[lid]]
                assert periods.parse_yyyymm(per) - 1 in months
                assert periods.parse_yyyymm(per) + 1 in months
            elif kind == "invalid_zero_balance_code":
                assert by_key[(lid, per)][0][8] == "06"
            elif kind == "rows_after_termination":
                rows = by_loan[lid]
                assert rows[-2][8] != ""
                assert rows[-1][1] == per
            elif kind == "modification_with_terminal_same_month":
                row = by_key[(lid, per)][0]
                assert row[7] == "Y"
                assert row[8] == "01"
            elif kind == "missing_zero_balance_effective_date":
                row = by_key[(lid, per)][0]
                assert row[8] != ""
                assert row[9] == ""
            elif kind == "duplicate_origination":
                assert orig_ids[lid] == 2
            else:
                pytest.fail(f"unknown anomaly kind {kind}")


def test_truth_is_coherent_and_matches_files(tiny_dataset: Path) -> None:
    affected = {a["loan_id"] for a in anomalies_of(tiny_dataset)}
    con = duckdb.connect()
    truth = con.sql(
        f"select * from read_parquet('{(tiny_dataset / 'truth').as_posix()}/*.parquet')"
    ).fetchnumpy()
    total = truth["true_prepay"] + truth["true_credit"] + truth["true_active"]
    np.testing.assert_allclose(total, 1.0, atol=1e-12)
    expected_code = {1: {"01"}, 2: {"02", "03", "09"}, 3: {"01"}, 5: {"15"}, 6: {"96"}}
    perf_rows: dict[tuple[str, str], Row] = {}
    for v in manifest(tiny_dataset)["vintages"]:
        for row in read_members(tiny_dataset, v["vintage"])[1]:
            perf_rows[(row[0], row[1])] = row
    checked = 0
    for lid, per, outcome in zip(truth["loan_id"], truth["period"], truth["outcome"], strict=True):
        if lid in affected:
            continue
        row = perf_rows[(str(lid), str(per))]
        if outcome == 0:
            assert row[8] == ""
        elif outcome == 4:
            assert row[7] == "Y"
        else:
            assert row[8] in expected_code[int(outcome)]
        checked += 1
    assert checked > 10_000


def test_first_six_months_upb_rounding_rule(tiny_dataset: Path) -> None:
    _, perf = read_members(tiny_dataset, 2018)
    young = [r for r in perf if int(r[4]) <= 6 and r[7] == "" and float(r[2]) > 500]
    assert young
    assert all(float(r[2]) % 1000 == 0 for r in young)


def test_loan_identifiers_are_unique_and_well_formed(tiny_dataset: Path) -> None:
    import re

    seen: set[str] = set()
    for v in manifest(tiny_dataset)["vintages"]:
        orig, _ = read_members(tiny_dataset, v["vintage"])
        ids = {r[19] for r in orig}
        assert all(re.fullmatch(LOAN_ID_PATTERN, i) for i in ids)
        assert all(i[1:3] == f"{v['vintage'] % 100:02d}" for i in ids)
        assert not ids & seen
        seen |= ids


def test_cli_synth_writes_dataset(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "synth",
            "--preset",
            "ci",
            "--out",
            str(tmp_path / "cli"),
            "--seed",
            "5",
            "--first-vintage",
            "2024",
            "--loans-per-vintage",
            "20",
            "--no-anomalies",
        ]
    )
    assert code == 0
    totals = json.loads(capsys.readouterr().out)
    assert totals["loans"] == 20 + 20 + 20  # partial 2026 vintage is floored at 20 loans
    assert not anomalies_of(tmp_path / "cli")
