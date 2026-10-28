"""Stream SFLLD sample archives into immutable bronze Parquet with row-level lineage.

Bronze preserves every field exactly as received (strings), plus ``_source_file``,
``_source_row`` (1-based line number in the member) and ``_violations`` (bit ``k-1`` set when
field ``k`` breaks its documented domain). Nothing is typed, imputed or dropped here.
Field-domain violations are *counted* for the quality report; loan-level quarantine decisions are
made downstream in dbt.

A vintage's outputs are reused when its input fingerprint (archive SHA-256, layout fingerprints,
ingest version, malformed-row policy) is unchanged and the recorded output hashes still match.
Any change rebuilds atomically, and the manifest is written last as the commit marker.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import zipfile
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from prepay.contracts.layout import Layout
from prepay.contracts.sflld import SAMPLE_ARCHIVE, layouts_for_release, sample_members
from prepay.contracts.validate import violation_mask
from prepay.ingest.lock import DataLock, LockedFile
from prepay.io import atomic_path, read_json, sha256_file, write_json_atomic

log = logging.getLogger(__name__)

INGEST_VERSION = "2"  # 2: adds the _violations bitmask column
BLOCK_BYTES = 8 << 20
MAX_REPORTED_LINES = 20


class IngestError(RuntimeError):
    """A source file failed validation; nothing was published for it."""


@dataclass(slots=True)
class MemberStats:
    member: str
    file_kind: str
    rows: int = 0
    malformed_rows: int = 0
    malformed_lines: list[int] = field(default_factory=list)  # first few, line numbers only
    violations: dict[str, int] = field(default_factory=dict)
    output: str = ""
    output_sha256: str = ""


def bronze_dir(bronze_root: Path, release: int, vintage: int) -> Path:
    return bronze_root / "sflld" / f"release={release}" / f"vintage={vintage}"


def bronze_schema(layout: Layout) -> pa.Schema:
    return pa.schema(
        [(name, pa.string()) for name in layout.column_names]
        + [("_source_file", pa.string()), ("_source_row", pa.int64()), ("_violations", pa.int64())]
    )


def _input_fingerprint(locked: LockedFile, release: int, allow_malformed: bool) -> str:
    origination, performance = layouts_for_release(release)
    payload = {
        "archive_sha256": locked.sha256,
        "release": release,
        "origination_layout": origination.fingerprint(),
        "performance_layout": performance.fingerprint(),
        "ingest_version": INGEST_VERSION,
        "allow_malformed": allow_malformed,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _source_lines(first_ordinal: int, count: int, malformed_sorted: list[int]) -> np.ndarray:
    """Map valid-row ordinals to physical line numbers, skipping malformed lines."""
    lines = np.arange(first_ordinal, first_ordinal + count, dtype=np.int64)
    for bad in malformed_sorted:
        lines[lines >= bad] += 1
    return lines


def stream_member(
    archive: zipfile.ZipFile, member: str, layout: Layout, target: Path, *, allow_malformed: bool
) -> MemberStats:
    """Parse one headerless member into a bronze Parquet file in bounded memory."""
    stats = MemberStats(member=member, file_kind=layout.file_kind)
    stats.violations = dict.fromkeys(layout.column_names, 0)
    malformed: list[int] = []

    def on_invalid(row: Any) -> str:
        malformed.append(int(row.number) if row.number is not None else -1)
        if not allow_malformed:
            return "error"
        return "skip"

    read_options = pacsv.ReadOptions(
        column_names=list(layout.column_names), block_size=BLOCK_BYTES, use_threads=False
    )
    parse_options = pacsv.ParseOptions(
        delimiter=layout.delimiter, quote_char=False, invalid_row_handler=on_invalid
    )
    convert_options = pacsv.ConvertOptions(
        column_types=dict.fromkeys(layout.column_names, pa.string()), strings_can_be_null=False
    )
    schema = bronze_schema(layout)
    ordinal = 1
    try:
        with (
            archive.open(member) as raw,
            pacsv.open_csv(raw, read_options, parse_options, convert_options) as reader,
            pq.ParquetWriter(str(target), schema, compression="zstd") as writer,
        ):
            for batch in reader:
                count = batch.num_rows
                lines = _source_lines(ordinal, count, sorted(m for m in malformed if m > 0))
                ordinal += count
                bitmask = np.zeros(count, dtype=np.int64)
                for spec in layout.fields:
                    bad = violation_mask(spec, batch.column(spec.name)).to_numpy(
                        zero_copy_only=False
                    )
                    stats.violations[spec.name] += int(bad.sum())
                    bitmask |= bad.astype(np.int64) << (spec.position - 1)
                columns = [batch.column(n) for n in layout.column_names]
                columns += [
                    pa.array([member] * count, pa.string()),
                    pa.array(lines),
                    pa.array(bitmask),
                ]
                writer.write_batch(pa.record_batch(columns, schema=schema))
                stats.rows += count
    except pa.ArrowInvalid as exc:
        where = f" (first malformed line {malformed[0]})" if malformed else ""
        raise IngestError(
            f"{member}: rows do not match the {layout.layout_id} {layout.file_kind} layout "
            f"({layout.width} fields){where}. Pass --allow-malformed to quarantine such rows."
        ) from exc
    stats.malformed_rows = len(malformed)
    stats.malformed_lines = malformed[:MAX_REPORTED_LINES]
    return stats


def _reusable(manifest_path: Path, fingerprint: str) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        return None
    manifest = read_json(manifest_path)
    if manifest.get("input_fingerprint") != fingerprint:
        return None
    for member in manifest["members"]:
        output = manifest_path.parent / member["output"]
        if not output.is_file() or sha256_file(output) != member["output_sha256"]:
            return None
    return dict(manifest)


def ingest_archive(
    raw_dir: Path, locked: LockedFile, lock: DataLock, bronze_root: Path, *, allow_malformed: bool
) -> dict[str, Any]:
    archive_path = raw_dir / locked.path
    match = SAMPLE_ARCHIVE.fullmatch(archive_path.name)
    if match is None:
        raise IngestError(f"{archive_path.name} is not named sample_YYYY.zip")
    vintage = int(match["vintage"])
    out_dir = bronze_dir(bronze_root, lock.release, vintage)
    manifest_path = out_dir / "_manifest.json"
    fingerprint = _input_fingerprint(locked, lock.release, allow_malformed)
    if (reused := _reusable(manifest_path, fingerprint)) is not None:
        log.info("bronze vintage reused", extra={"vintage": vintage})
        return {**reused, "status": "reused"}

    started = time.perf_counter()
    if sha256_file(archive_path) != locked.sha256:
        raise IngestError(f"{locked.path}: SHA-256 differs from data lock; refusing to ingest")
    origination, performance = layouts_for_release(lock.release)
    expected = list(sample_members(vintage))
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise IngestError(f"{locked.path}: not a valid ZIP archive") from exc
    with archive:
        names = archive.namelist()
        if sorted(names) != sorted(expected):
            raise IngestError(f"{locked.path}: members {names} differ from expected {expected}")
        try:
            corrupt = archive.testzip()
        except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
            raise IngestError(f"{locked.path}: archive data is corrupt") from exc
        if corrupt is not None:
            raise IngestError(f"{locked.path}: CRC check failed for {corrupt}")
        out_dir.mkdir(parents=True, exist_ok=True)
        members = []
        for member, layout, output in zip(
            expected,
            (origination, performance),
            ("origination.parquet", "performance.parquet"),
            strict=True,
        ):
            with atomic_path(out_dir / output) as tmp:
                stats = stream_member(archive, member, layout, tmp, allow_malformed=allow_malformed)
            stats.output = output
            stats.output_sha256 = sha256_file(out_dir / output)
            members.append(stats)

    manifest = {
        "kind": "prepay-bronze-sflld",
        "synthetic": lock.synthetic,
        "release": lock.release,
        "vintage": vintage,
        "layout_id": origination.layout_id,
        "origination_layout_fingerprint": origination.fingerprint(),
        "performance_layout_fingerprint": performance.fingerprint(),
        "ingest_version": INGEST_VERSION,
        "allow_malformed": allow_malformed,
        "archive": {"path": locked.path, "bytes": locked.bytes, "sha256": locked.sha256},
        "input_fingerprint": fingerprint,
        "members": [asdict(m) for m in members],
    }
    write_json_atomic(manifest_path, manifest)
    log.info(
        "bronze vintage written",
        extra={
            "vintage": vintage,
            "rows": {m.file_kind: m.rows for m in members},
            "malformed": {m.file_kind: m.malformed_rows for m in members},
            "seconds": round(time.perf_counter() - started, 3),
        },
    )
    return {**manifest, "status": "written"}
