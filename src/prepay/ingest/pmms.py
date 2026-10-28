"""Freddie Mac PMMS weekly mortgage rates from FRED: strict CSV parsing, bronze, local fetch.

FRED's ``fredgraph.csv`` format (verified 2026-10-28): header ``observation_date,<SERIES>``, ISO
dates ascending, one weekly observation per row, values in percent per year. FRED marks
missing observations with ``.`` (historically) or an empty field; both become explicit nulls.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from prepay.ingest.lock import DataLock, LockedFile
from prepay.io import atomic_path, read_json, sha256_file, write_json_atomic

log = logging.getLogger(__name__)

PMMS_INGEST_VERSION = "1"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
#: Freddie Mac switched PMMS to application-based estimates on this date (FRED note, 2022-11).
METHOD_CHANGE_DATE = dt.date(2022, 11, 17)
PLAUSIBLE_PERCENT = (0.5, 25.0)
_SERIES = re.compile(r"MORTGAGE(15|30)US")


class PmmsFormatError(ValueError):
    """The CSV does not follow the documented FRED format."""


@dataclass(frozen=True, slots=True)
class Observations:
    series: str
    dates: tuple[dt.date, ...]
    rate_pct: tuple[float | None, ...]
    source_rows: tuple[int, ...]  # 1-based line numbers (header is line 1)

    @property
    def missing(self) -> int:
        return sum(v is None for v in self.rate_pct)


def parse_fred_csv(text: str, expected_series: str) -> Observations:
    lines = text.splitlines()
    if not lines:
        raise PmmsFormatError("empty file")
    header = lines[0].strip()
    if header not in (f"observation_date,{expected_series}", f"DATE,{expected_series}"):
        raise PmmsFormatError(f"header {header!r} is not a FRED {expected_series} header")
    dates: list[dt.date] = []
    values: list[float | None] = []
    rows: list[int] = []
    for number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) != 2:
            raise PmmsFormatError(f"line {number}: expected 2 fields, found {len(parts)}")
        try:
            day = dt.date.fromisoformat(parts[0])
        except ValueError as exc:
            raise PmmsFormatError(f"line {number}: invalid date {parts[0]!r}") from exc
        if dates and day <= dates[-1]:
            raise PmmsFormatError(f"line {number}: dates must be strictly increasing")
        raw = parts[1].strip()
        if raw in ("", "."):
            value: float | None = None
        else:
            try:
                value = float(raw)
            except ValueError as exc:
                raise PmmsFormatError(f"line {number}: non-numeric rate {raw!r}") from exc
            low, high = PLAUSIBLE_PERCENT
            if not low <= value <= high:
                raise PmmsFormatError(f"line {number}: rate {value} outside {PLAUSIBLE_PERCENT} %")
        dates.append(day)
        values.append(value)
        rows.append(number)
    if not dates:
        raise PmmsFormatError("no observations")
    return Observations(expected_series, tuple(dates), tuple(values), tuple(rows))


def ingest_series(
    raw_dir: Path, locked: LockedFile, lock: DataLock, bronze_root: Path
) -> dict[str, Any]:
    path = raw_dir / locked.path
    series = path.stem
    if _SERIES.fullmatch(series) is None:
        raise PmmsFormatError(f"unexpected PMMS series file {path.name}")
    out_dir = bronze_root / "pmms" / f"series={series}"
    manifest_path = out_dir / "_manifest.json"
    fingerprint = hashlib.sha256(f"{locked.sha256}:{PMMS_INGEST_VERSION}".encode()).hexdigest()
    if manifest_path.is_file():
        previous = read_json(manifest_path)
        output = out_dir / "observations.parquet"
        if (
            previous.get("input_fingerprint") == fingerprint
            and output.is_file()
            and sha256_file(output) == previous["output_sha256"]
        ):
            return {**previous, "status": "reused"}
    if sha256_file(path) != locked.sha256:
        raise PmmsFormatError(f"{locked.path}: SHA-256 differs from data lock")
    obs = parse_fred_csv(path.read_text(encoding="utf-8"), series)
    table = pa.table(
        {
            "observation_date": pa.array(obs.dates, pa.date32()),
            "rate_pct": pa.array(obs.rate_pct, pa.float64()),
            "_source_file": pa.array([path.name] * len(obs.dates), pa.string()),
            "_source_row": pa.array(obs.source_rows, pa.int64()),
        }
    )
    output = out_dir / "observations.parquet"
    out_dir.mkdir(parents=True, exist_ok=True)
    with atomic_path(output) as tmp:
        pq.write_table(table, str(tmp), compression="zstd")
    manifest = {
        "kind": "prepay-bronze-pmms",
        "synthetic": lock.synthetic,
        "series": series,
        "source": {"path": locked.path, "sha256": locked.sha256, "bytes": locked.bytes},
        "observations": len(obs.dates),
        "missing_observations": obs.missing,
        "first_date": obs.dates[0].isoformat(),
        "last_date": obs.dates[-1].isoformat(),
        "units": "percent per year",
        "method_change_date": METHOD_CHANGE_DATE.isoformat(),
        "input_fingerprint": fingerprint,
        "output_sha256": sha256_file(output),
    }
    write_json_atomic(manifest_path, manifest)
    return {**manifest, "status": "written"}


def fetch_series(series: str, out_dir: Path, *, timeout: float = 120.0) -> dict[str, Any]:
    """Download one FRED series CSV (local research use only; never run in CI).

    Writes ``<series>.csv`` and a ``<series>.retrieval.json`` sidecar recording URL, UTC
    retrieval time, byte count and SHA-256. The CSV is validated before it is published.
    """
    if _SERIES.fullmatch(series) is None:
        raise ValueError(f"unsupported series {series}")
    url = FRED_CSV_URL.format(series=series)
    request = urllib.request.Request(url, headers={"User-Agent": "prepay-research"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        body: bytes = response.read()
    parse_fred_csv(body.decode("utf-8"), series)
    target = out_dir / f"{series}.csv"
    with atomic_path(target) as tmp:
        tmp.write_bytes(body)
    sidecar = {
        "series": series,
        "url": url,
        "retrieved_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }
    write_json_atomic(out_dir / f"{series}.retrieval.json", sidecar)
    log.info("fetched FRED series", extra={k: v for k, v in sidecar.items() if k != "url"})
    return sidecar
