from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from prepay.cli import main
from prepay.resources import host_description, peak_rss_bytes


def test_peak_rss_is_positive_and_grows_with_allocation() -> None:
    # A fresh process: in this test session other tests may already have raised the peak.
    script = (
        "from prepay.resources import peak_rss_bytes\n"
        "before = peak_rss_bytes()\n"
        "block = bytearray(64 * 2**20)\n"
        "block[::4096] = b'x' * len(block[::4096])\n"
        "print(before, peak_rss_bytes())\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    ).stdout.split()
    before, after = int(out[0]), int(out[1])
    assert before > 0
    assert after >= before + 32 * 2**20
    assert peak_rss_bytes() > 0


def test_host_description_names_cpu_and_python() -> None:
    host = host_description()
    assert host["python"]
    assert isinstance(host["logical_cpus"], int)


def test_cli_writes_resource_report_when_requested(
    tiny_dataset: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = tmp_path / "report.json"
    monkeypatch.setenv("PREPAY_RESOURCE_REPORT", str(report))
    code = main(
        [
            "data-lock",
            "create",
            "--raw-dir",
            str(tiny_dataset / "raw"),
            "--synthetic-manifest",
            str(tiny_dataset / "manifest.json"),
            "--out",
            str(tmp_path / "lock.json"),
        ]
    )
    assert code == 0
    measured = json.loads(report.read_text())
    assert measured["peak_rss_bytes"] > 0
    assert measured["seconds"] >= 0
