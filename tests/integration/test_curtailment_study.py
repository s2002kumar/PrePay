"""F1 curtailment study on the synthetic pipeline (silver states + bronze DDLPI)."""

from __future__ import annotations

import json
from pathlib import Path

from prepay import periods
from prepay.cli import main
from prepay.evaluation.curtailment import study
from prepay.ingest.lock import DataLock, write_lock


def test_study_separates_the_conventions_on_recast_synthetic_data(
    built: tuple[Path, DataLock],
) -> None:
    root, _ = built
    report = study(
        root, through_month=periods.month(2019, 12), sample_fraction=None, synthetic=True
    )
    assert report["rows"] > 1000
    no_recast = report["conventions"]["no_recast"]["by_reporting_regime"]
    recast = report["conventions"]["recast"]["by_reporting_regime"]
    assert {"cycle_16th_to_15th", "calendar_month"} <= set(recast)
    # The generator re-amortizes after curtailments (SYNTHETIC_DATA.md), so the recast
    # convention explains its one-installment months better than no-recast does.
    share = "one_installment_within_dead_band_share"
    assert recast["calendar_month"][share] > 0.8
    assert recast["calendar_month"][share] >= no_recast["calendar_month"][share]
    exclusions = recast["calendar_month"]["exclusions"]
    assert exclusions.get("balance may be rounded to $1,000", 0) > 0
    assert isinstance(report["decision"]["defensible"], bool)


def test_curtailment_command_writes_aggregates_only(
    built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    lock_path = tmp_path / "lock.json"
    write_lock(lock, lock_path)
    out = tmp_path / "curtailments.json"
    code = main(
        [
            "diagnose",
            "curtailments",
            "--data-root",
            str(root),
            "--lock",
            str(lock_path),
            "--out",
            str(out),
            "--sample-fraction",
            "0.5",
        ]
    )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    report = json.loads(text)
    assert report["synthetic"] is True
    assert "loan_id" not in text
