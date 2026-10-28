"""Write a complete synthetic source dataset: SFLLD-format ZIPs, FRED-format rates, truth, manifest.

Layout of ``out_dir`` (mirrors what a researcher's private ``data/raw`` would hold)::

    raw/sflld/sample_YYYY.zip       sample_orig_YYYY.txt + sample_perf_YYYY.txt (headerless, |)
    raw/pmms/MORTGAGE30US.csv       FRED fredgraph.csv format (synthetic values)
    raw/pmms/MORTGAGE15US.csv
    truth/truth_YYYY.parquet        ground-truth hazards and outcomes per at-risk loan-month
    manifest.json                   config, layout fingerprints, hashes, row counts, anomalies

Everything is deterministic for a given config and code version. Archive member *contents* are
byte-identical across platforms; compressed archive bytes can differ between zlib builds, so both
hashes are recorded.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from prepay import periods
from prepay.contracts.sflld import LAYOUT_ID, ORIGINATION, PERFORMANCE, sample_members
from prepay.io import atomic_path, sha256_file, write_json_atomic
from prepay.synthetic import anomalies, rates
from prepay.synthetic.config import SyntheticConfig
from prepay.synthetic.render import origination_table, performance_table, truth_table
from prepay.synthetic.simulate import RateLookup, SimulatedBlock, block_rng, originate, simulate

log = logging.getLogger(__name__)

RATE_HISTORY_START = periods.month(1999, 1)
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
WRITE_OPTIONS = pacsv.WriteOptions(include_header=False, delimiter="|", quoting_style="none")


@dataclass(frozen=True, slots=True)
class MemberInfo:
    name: str
    rows: int
    bytes: int
    sha256: str


def _hash_text_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    rows = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            rows += chunk.count(b"\n")
    return rows, digest.hexdigest()


def _write_zip(target: Path, members: list[tuple[str, Path]]) -> None:
    with atomic_path(target) as tmp, zipfile.ZipFile(tmp, "w") as archive:
        for name, source in members:
            info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with source.open("rb") as src, archive.open(info, "w", force_zip64=True) as dst:
                shutil.copyfileobj(src, dst, 1 << 20)


def write_rates(
    config: SyntheticConfig, out_dir: Path
) -> tuple[RateLookup, list[dict[str, object]]]:
    weekly = rates.generate(config.seed, config.cutoff_month)
    entries: list[dict[str, object]] = []
    for series in ("MORTGAGE30US", "MORTGAGE15US"):
        target = out_dir / "raw" / "pmms" / f"{series}.csv"
        with atomic_path(target) as tmp:
            tmp.write_text(weekly.to_fred_csv(series), encoding="utf-8", newline="\n")
        entries.append(
            {
                "path": target.relative_to(out_dir).as_posix(),
                "series": series,
                "observations": len(weekly.dates),
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        )
    r30, r15 = rates.month_end_asof(weekly, RATE_HISTORY_START, config.cutoff_month)
    return RateLookup(RATE_HISTORY_START, r30, r15), entries


def write_vintage(
    config: SyntheticConfig, vintage: int, lookup: RateLookup, out_dir: Path, work_dir: Path
) -> dict[str, object]:
    loans = config.loans_in(vintage)
    orig_name, perf_name = sample_members(vintage)
    orig_path, perf_path = work_dir / orig_name, work_dir / perf_name
    truth_target = out_dir / "truth" / f"truth_{vintage}.parquet"
    applied: list[anomalies.Anomaly] = []
    orig_schema = pa.schema([(n, pa.string()) for n in ORIGINATION.column_names])
    perf_schema = pa.schema([(n, pa.string()) for n in PERFORMANCE.column_names])

    with (
        atomic_path(truth_target) as truth_tmp,
        pa.OSFile(str(orig_path), "wb") as orig_sink,
        pa.OSFile(str(perf_path), "wb") as perf_sink,
        pacsv.CSVWriter(orig_sink, orig_schema, write_options=WRITE_OPTIONS) as orig_out,
        pacsv.CSVWriter(perf_sink, perf_schema, write_options=WRITE_OPTIONS) as perf_out,
    ):
        truth_writer: pq.ParquetWriter | None = None
        for block, first in enumerate(range(0, loans, config.block_size)):
            count = min(config.block_size, loans - first)
            rng = block_rng(config.seed, vintage, block)
            origination = originate(rng, vintage, count, first, config.cutoff_month, lookup)
            grid, truth = simulate(rng, origination, config.cutoff_month, lookup)
            simulated = SimulatedBlock(vintage, block, origination, grid, truth)
            render_rng = block_rng(config.seed, vintage, 1_000_000 + block)
            orig_table = origination_table(simulated, render_rng)
            perf_table = performance_table(simulated, render_rng, config.cutoff_month)
            if config.anomalies and block == 0:
                anomaly_rng = block_rng(config.seed, vintage, 2_000_000)
                orig_table, perf_table, applied = anomalies.inject(
                    anomaly_rng, vintage, orig_table, perf_table
                )
            orig_out.write_table(orig_table)
            perf_out.write_table(perf_table)
            t_table = truth_table(simulated)
            if truth_writer is None:
                truth_writer = pq.ParquetWriter(str(truth_tmp), t_table.schema, compression="zstd")
            truth_writer.write_table(t_table)
        if truth_writer is not None:
            truth_writer.close()

    archive = out_dir / "raw" / "sflld" / f"sample_{vintage}.zip"
    _write_zip(archive, [(orig_name, orig_path), (perf_name, perf_path)])
    members = []
    for name, path in ((orig_name, orig_path), (perf_name, perf_path)):
        rows, digest = _hash_text_file(path)
        members.append(MemberInfo(name, rows, path.stat().st_size, digest))
        path.unlink()
    log.info(
        "synthetic vintage written",
        extra={"vintage": vintage, "loans": loans, "performance_rows": members[1].rows},
    )
    return {
        "vintage": vintage,
        "loans": loans,
        "archive": {
            "path": archive.relative_to(out_dir).as_posix(),
            "bytes": archive.stat().st_size,
            "sha256": sha256_file(archive),
        },
        "members": [asdict(m) for m in members],
        "performance_rows": members[1].rows,
        "truth": {
            "path": truth_target.relative_to(out_dir).as_posix(),
            "sha256": sha256_file(truth_target),
        },
        "anomalies": [a.as_dict() for a in applied],
    }


def generate_dataset(config: SyntheticConfig, out_dir: Path) -> dict[str, object]:
    """Generate the full dataset into ``out_dir`` and return the manifest (also written)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir = out_dir / ".work"
    work_dir.mkdir(exist_ok=True)
    lookup, rate_entries = write_rates(config, out_dir)
    vintages = [
        write_vintage(config, v, lookup, out_dir, work_dir)
        for v in range(config.first_vintage, config.last_vintage + 1)
    ]
    shutil.rmtree(work_dir)
    manifest: dict[str, object] = {
        "kind": "prepay-synthetic-source-dataset",
        "synthetic": True,
        "notice": "Fictional data generated by prepay.synthetic; not Freddie Mac data.",
        "config": config.as_dict(),
        "layout": {
            "id": LAYOUT_ID,
            "origination_fingerprint": ORIGINATION.fingerprint(),
            "performance_fingerprint": PERFORMANCE.fingerprint(),
        },
        "rates": rate_entries,
        "vintages": vintages,
        "totals": {
            "loans": sum(
                config.loans_in(v) for v in range(config.first_vintage, config.last_vintage + 1)
            ),
            "performance_rows": sum(_int(v["performance_rows"]) for v in vintages),
        },
    }
    write_json_atomic(out_dir / "manifest.json", manifest)
    return manifest


def _int(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError(f"expected int, got {type(value).__name__}")
    return value
