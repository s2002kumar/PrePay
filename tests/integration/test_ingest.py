"""Bronze ingest: exact lineage, idempotency, and deterministic rejection of bad inputs."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import duckdb
import pytest

from prepay.ingest import ingest_all
from prepay.ingest.lock import LockError, create_lock, read_lock, verify_lock, write_lock
from prepay.ingest.sflld import IngestError, bronze_dir
from prepay.io import sha256_file

ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@pytest.fixture
def raw(tiny_dataset: Path, tmp_path: Path) -> Path:
    """A private, mutable copy of the tiny dataset's raw directory."""
    target = tmp_path / "raw"
    shutil.copytree(tiny_dataset / "raw", target)
    return target


def lock_for(raw: Path, tiny_dataset: Path):
    return create_lock(
        raw, release=48, terms_reference="", synthetic_manifest=tiny_dataset / "manifest.json"
    )


def bronze_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*.parquet"))}


def test_bronze_preserves_every_field_with_exact_lineage(
    raw: Path, tiny_dataset: Path, tmp_path: Path
) -> None:
    lock = lock_for(raw, tiny_dataset)
    summary = ingest_all(raw, lock, tmp_path / "bronze")
    assert summary["synthetic"] is True
    manifest = json.loads((tiny_dataset / "manifest.json").read_text(encoding="utf-8"))
    con = duckdb.connect()
    for entry in manifest["vintages"]:
        vintage = entry["vintage"]
        out = bronze_dir(tmp_path / "bronze", 48, vintage)
        with zipfile.ZipFile(raw / "sflld" / f"sample_{vintage}.zip") as archive:
            for kind, member in (("origination", 0), ("performance", 1)):
                name = entry["members"][member]["name"]
                lines = archive.read(name).decode("utf-8").splitlines()
                rows = con.sql(
                    f"select * exclude (_source_file, _source_row), _source_file, _source_row "
                    f"from read_parquet('{(out / f'{kind}.parquet').as_posix()}', "
                    f"hive_partitioning=false) "
                    f"order by _source_row"
                ).fetchall()
                assert len(rows) == len(lines) == entry["members"][member]["rows"]
                for number, (row, line) in enumerate(zip(rows, lines, strict=True), start=1):
                    assert "|".join(row[:-2]) == line  # byte-exact field preservation
                    assert row[-2] == name
                    assert row[-1] == number


def test_violation_counts_match_injected_anomalies(
    raw: Path, tiny_dataset: Path, tmp_path: Path
) -> None:
    summary = ingest_all(raw, lock_for(raw, tiny_dataset), tmp_path / "bronze")
    manifest = json.loads((tiny_dataset / "manifest.json").read_text(encoding="utf-8"))
    injected = sum(
        a["kind"] == "invalid_zero_balance_code"
        for v in manifest["vintages"]
        for a in v["anomalies"]
    )
    reported = sum(
        v["field_violations"]["performance"].get("zero_balance_code", 0)
        for v in summary["vintages"].values()
    )
    assert injected > 0
    assert reported == injected
    others = [
        (k, f)
        for v in summary["vintages"].values()
        for k, f in v["field_violations"].items()
        if set(f) - {"zero_balance_code"}
    ]
    assert not others


def test_rerun_reuses_outputs_and_detects_tampering(
    raw: Path, tiny_dataset: Path, tmp_path: Path
) -> None:
    bronze = tmp_path / "bronze"
    lock = lock_for(raw, tiny_dataset)
    first = ingest_all(raw, lock, bronze)
    assert {v["status"] for v in first["vintages"].values()} == {"written"}
    before = bronze_hashes(bronze)
    second = ingest_all(raw, lock, bronze)
    assert {v["status"] for v in second["vintages"].values()} == {"reused"}
    assert bronze_hashes(bronze) == before

    victim = bronze_dir(bronze, 48, 2019) / "performance.parquet"
    victim.write_bytes(b"corrupted")
    third = ingest_all(raw, lock, bronze)
    assert third["vintages"]["2019"]["status"] == "written"
    assert third["vintages"]["2020"]["status"] == "reused"
    assert bronze_hashes(bronze) == before


def test_changed_source_is_refused_until_relocked(
    raw: Path, tiny_dataset: Path, tmp_path: Path
) -> None:
    lock = lock_for(raw, tiny_dataset)
    archive = raw / "sflld" / "sample_2016.zip"
    _rewrite_member(archive, "sample_perf_2016.txt", lambda lines: lines[:-1])
    assert "size changed: sflld/sample_2016.zip" in verify_lock(lock, raw)
    with pytest.raises(LockError, match="verification failed"):
        ingest_all(raw, lock, tmp_path / "bronze")
    relocked = lock_for(raw, tiny_dataset)
    assert ingest_all(raw, relocked, tmp_path / "bronze")["vintages"]["2016"]["status"] == "written"


def _rewrite_member(archive: Path, member: str, edit) -> None:
    with zipfile.ZipFile(archive) as src:
        contents = {name: src.read(name).decode("utf-8") for name in src.namelist()}
    lines = contents[member].splitlines()
    contents[member] = "\n".join(edit(lines)) + "\n"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as dst:
        for name, text in contents.items():
            dst.writestr(zipfile.ZipInfo(name, ZIP_TIME), text)


def test_malformed_row_stops_run_unless_quarantined(
    raw: Path, tiny_dataset: Path, tmp_path: Path
) -> None:
    archive = raw / "sflld" / "sample_2017.zip"
    _rewrite_member(
        archive,
        "sample_perf_2017.txt",
        lambda lines: [*lines[:9], "|".join(lines[9].split("|")[:34]), *lines[10:]],
    )
    lock = lock_for(raw, tiny_dataset)
    with pytest.raises(IngestError, match=r"first malformed line 10"):
        ingest_all(raw, lock, tmp_path / "strict")
    assert not (bronze_dir(tmp_path / "strict", 48, 2017) / "_manifest.json").exists()

    summary = ingest_all(raw, lock, tmp_path / "lenient", allow_malformed=True)
    assert summary["vintages"]["2017"]["malformed_rows"]["performance"] == 1
    rows = duckdb.sql(
        "select _source_row from read_parquet('"
        + (bronze_dir(tmp_path / "lenient", 48, 2017) / "performance.parquet").as_posix()
        + "') order by _source_row"
    ).fetchall()
    numbers = [r[0] for r in rows]
    assert 10 not in numbers
    assert numbers[:11] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12]


def test_pre_release_47_width_is_rejected(raw: Path, tiny_dataset: Path, tmp_path: Path) -> None:
    archive = raw / "sflld" / "sample_2018.zip"
    # Pre-R47 origination files had 32 fields; simulate by appending one field to every row.
    _rewrite_member(archive, "sample_orig_2018.txt", lambda lines: [ln + "|7" for ln in lines])
    with pytest.raises(IngestError, match="31 fields"):
        ingest_all(raw, lock_for(raw, tiny_dataset), tmp_path / "bronze")


@pytest.mark.parametrize("damage", ["truncate", "flip", "extra_member"])
def test_damaged_archives_are_rejected(
    raw: Path, tiny_dataset: Path, tmp_path: Path, damage: str
) -> None:
    archive = raw / "sflld" / "sample_2015.zip"
    data = bytearray(archive.read_bytes())
    if damage == "truncate":
        archive.write_bytes(bytes(data[: len(data) // 2]))
    elif damage == "flip":
        data[200] ^= 0xFF  # inside the first member's compressed stream
        archive.write_bytes(bytes(data))
    else:
        with zipfile.ZipFile(archive, "a") as z:
            z.writestr(zipfile.ZipInfo("notes.txt", ZIP_TIME), "x")
    with pytest.raises(IngestError):
        ingest_all(raw, lock_for(raw, tiny_dataset), tmp_path / "bronze")


def test_lock_rules_for_real_data(raw: Path, tmp_path: Path) -> None:
    with pytest.raises(LockError, match="terms_reference"):
        create_lock(raw, release=48, terms_reference=" ")
    with pytest.raises(LockError, match="no verified layout"):
        create_lock(raw, release=46, terms_reference="accepted 2026-10-28")
    lock = create_lock(raw, release=47, terms_reference="Clarity registration 2026-10-28")
    assert lock.synthetic is False
    assert lock.performance_cutoff == "2026-03-31"
    write_lock(lock, tmp_path / "data.lock.json")
    assert read_lock(tmp_path / "data.lock.json") == lock
    (raw / "sflld" / "sample_2014.zip").write_bytes(b"PK")
    assert "not in lock: sflld/sample_2014.zip" in verify_lock(lock, raw)
    (raw / "sflld" / "readme.txt").write_text("x")
    with pytest.raises(LockError, match="unexpected files"):
        create_lock(raw, release=48, terms_reference="ok")


def test_malformed_lock_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "lock.json"
    path.write_text(json.dumps({"version": 1, "dataset": "x"}))
    with pytest.raises(LockError, match="malformed"):
        read_lock(path)
    path.write_text(json.dumps({"version": 99}))
    with pytest.raises(LockError, match="unsupported"):
        read_lock(path)


def test_cli_lock_and_ingest_round_trip(
    raw: Path, tiny_dataset: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from prepay.cli import main

    lock_path = tmp_path / "data.lock.json"
    assert (
        main(
            [
                "data-lock",
                "create",
                "--raw-dir",
                str(raw),
                "--out",
                str(lock_path),
                "--synthetic-manifest",
                str(tiny_dataset / "manifest.json"),
            ]
        )
        == 0
    )
    assert main(["data-lock", "verify", "--raw-dir", str(raw), "--lock", str(lock_path)]) == 0
    assert (
        main(
            [
                "ingest",
                "--raw-dir",
                str(raw),
                "--lock",
                str(lock_path),
                "--data-root",
                str(tmp_path / "data"),
            ]
        )
        == 0
    )
    (raw / "pmms" / "MORTGAGE30US.csv").write_text("observation_date,MORTGAGE30US\n")
    assert main(["data-lock", "verify", "--raw-dir", str(raw), "--lock", str(lock_path)]) == 2
    output = io.StringIO(capsys.readouterr().out)
    assert "size changed: pmms/MORTGAGE30US.csv" in output.getvalue()
