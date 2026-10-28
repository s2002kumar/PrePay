"""Publication gate: catches restricted content, and this repository passes it.

Fixture strings are built by concatenation so this file never contains a contiguous match itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from prepay.publication import scan_file, scan_repository, scan_text, scan_tree

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("F21Q1000123" + "4|202101|250000.00|00|1|359|||", "sflld_performance_row"),
        ("|".join(["x"] * 31), "wide_pipe_row"),
        ("loan F99Q10001234 paid off", "loan_identifier"),
        ("key = AKIA" + "ABCDEFGHIJKLMNOP", "aws_access_key"),
        ("-----BEGIN RSA " + "PRIVATE KEY-----", "private_key"),
        ("tok" + "en = 'abcdefghijklmnopqrstuvwxyz012345'", "generic_secret_assignment"),
    ],
)
def test_restricted_content_is_detected(text: str, rule: str) -> None:
    assert rule in {f.rule for f in scan_text("x", text)}


def test_ordinary_text_passes() -> None:
    assert scan_text("x", "Cash WAL 7.2 years | CPR 12% | fictional pool") == []


@pytest.mark.parametrize(
    "relative",
    [
        "data/raw/sflld/sample_2021.zip",
        "notes/M1.md",
        ".env",
        "x/model.pkl",
        "panel.parquet",
        "warehouse/prepay.duckdb",
        "sample_perf_2021.txt",
    ],
)
def test_forbidden_paths(tmp_path: Path, relative: str) -> None:
    path = tmp_path / "f"
    path.write_text("x")
    assert any(f.rule == "forbidden_path" for f in scan_file(path, relative))


def test_tree_scan_labels_findings(tmp_path: Path) -> None:
    (tmp_path / "leak.txt").write_text("F21Q1000123" + "4|202101|1|")
    findings = scan_tree(tmp_path, "web")
    assert findings
    assert findings[0].location.startswith("web:")


def test_this_repository_tracked_set_is_publishable() -> None:
    findings = scan_repository(ROOT)
    assert findings == [], findings
