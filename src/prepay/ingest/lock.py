"""``data.lock.json``: the immutable list of source files a pipeline run is allowed to read.

The lock records file names, byte counts, SHA-256 digests, the declared SFLLD release and its
cutoffs, and the researcher's terms-of-use reference. It never contains rows, loan identifiers or
credentials, so it can be committed. Ingest refuses any file whose bytes differ from the lock.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from prepay import periods
from prepay.contracts.sflld import LAYOUT_ID, RELEASES, SAMPLE_ARCHIVE
from prepay.io import read_json, sha256_file, write_json_atomic

LOCK_VERSION = 1
SFLLD_DIR = "sflld"
PMMS_DIR = "pmms"
PMMS_SERIES = ("MORTGAGE30US", "MORTGAGE15US")


class LockError(ValueError):
    """The lock is malformed or the files on disk do not match it."""


@dataclass(frozen=True, slots=True)
class LockedFile:
    path: str  # POSIX path relative to the raw-data root
    bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class DataLock:
    version: int
    dataset: str
    synthetic: bool
    release: int
    layout_id: str
    origination_cutoff: str  # YYYY-MM-DD
    performance_cutoff: str  # YYYY-MM-DD
    terms_reference: str
    sflld: tuple[LockedFile, ...]
    pmms: tuple[LockedFile, ...]

    @property
    def performance_cutoff_month(self) -> str:
        return self.performance_cutoff[:7]

    def to_json(self) -> dict[str, object]:
        payload = asdict(self)
        payload["sflld"] = [asdict(f) for f in self.sflld]
        payload["pmms"] = [asdict(f) for f in self.pmms]
        return payload

    def fingerprint(self) -> str:
        canonical = json.dumps(self.to_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> DataLock:
        try:
            if payload["version"] != LOCK_VERSION:
                raise LockError(f"unsupported lock version {payload['version']}")

            def files(key: str) -> tuple[LockedFile, ...]:
                return tuple(
                    LockedFile(path=str(e["path"]), bytes=int(e["bytes"]), sha256=str(e["sha256"]))
                    for e in payload[key]
                )

            return cls(
                version=int(payload["version"]),
                dataset=str(payload["dataset"]),
                synthetic=bool(payload["synthetic"]),
                release=int(payload["release"]),
                layout_id=str(payload["layout_id"]),
                origination_cutoff=str(payload["origination_cutoff"]),
                performance_cutoff=str(payload["performance_cutoff"]),
                terms_reference=str(payload["terms_reference"]),
                sflld=files("sflld"),
                pmms=files("pmms"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise LockError(f"malformed data lock: {exc}") from exc


def _locked(raw_dir: Path, path: Path) -> LockedFile:
    return LockedFile(path.relative_to(raw_dir).as_posix(), path.stat().st_size, sha256_file(path))


def _scan(raw_dir: Path) -> tuple[tuple[LockedFile, ...], tuple[LockedFile, ...]]:
    archives = sorted(
        p for p in (raw_dir / SFLLD_DIR).glob("*.zip") if SAMPLE_ARCHIVE.fullmatch(p.name)
    )
    if not archives:
        raise LockError(f"no sample_YYYY.zip archives under {raw_dir / SFLLD_DIR}")
    unexpected = sorted(
        p.name
        for p in (raw_dir / SFLLD_DIR).iterdir()
        if p.is_file() and not SAMPLE_ARCHIVE.fullmatch(p.name)
    )
    if unexpected:
        raise LockError(f"unexpected files in {SFLLD_DIR}/: {unexpected}")
    rates = [raw_dir / PMMS_DIR / f"{series}.csv" for series in PMMS_SERIES]
    missing = [p.name for p in rates if not p.is_file()]
    if missing:
        raise LockError(f"missing PMMS series files: {missing}")
    return tuple(_locked(raw_dir, p) for p in archives), tuple(_locked(raw_dir, p) for p in rates)


def create_lock(
    raw_dir: Path, *, release: int, terms_reference: str, synthetic_manifest: Path | None = None
) -> DataLock:
    """Hash every source file under ``raw_dir`` and declare the release they belong to.

    For real data the release must be one with a verified layout and ``terms_reference`` must
    say how the researcher accepted Freddie Mac's dataset terms. For synthetic data, the release
    and cutoff come from the generator manifest.
    """
    sflld, pmms = _scan(raw_dir)
    if synthetic_manifest is not None:
        config = read_json(synthetic_manifest)["config"]
        cutoff_month = str(config["cutoff"])
        last_day = f"{cutoff_month}-{_days_in(cutoff_month):02d}"
        return DataLock(
            LOCK_VERSION,
            "prepay-synthetic",
            True,
            int(config["release"]),
            LAYOUT_ID,
            last_day,
            last_day,
            "not applicable: fictional data",
            sflld,
            pmms,
        )
    if release not in RELEASES:
        raise LockError(f"release {release} has no verified layout; supported: {sorted(RELEASES)}")
    if not terms_reference.strip():
        raise LockError("terms_reference is required for real Freddie Mac data")
    info = RELEASES[release]
    return DataLock(
        LOCK_VERSION,
        "freddie-mac-sflld-standard-sample",
        False,
        release,
        info.layout_id,
        info.origination_cutoff,
        info.performance_cutoff,
        terms_reference.strip(),
        sflld,
        pmms,
    )


def _days_in(yyyy_mm: str) -> int:
    return periods.last_day(periods.parse_iso(yyyy_mm)).day


def verify_lock(lock: DataLock, raw_dir: Path) -> list[str]:
    """Return every mismatch between the lock and the files on disk (empty when they agree)."""
    problems: list[str] = []
    for entry in (*lock.sflld, *lock.pmms):
        path = raw_dir / entry.path
        if not path.is_file():
            problems.append(f"missing: {entry.path}")
        elif path.stat().st_size != entry.bytes:
            problems.append(f"size changed: {entry.path}")
        elif sha256_file(path) != entry.sha256:
            problems.append(f"content changed (sha256): {entry.path}")
    locked = {e.path for e in lock.sflld}
    for path in sorted((raw_dir / SFLLD_DIR).glob("*.zip")):
        rel = path.relative_to(raw_dir).as_posix()
        if rel not in locked:
            problems.append(f"not in lock: {rel}")
    if lock.layout_id != LAYOUT_ID:
        problems.append(f"lock layout {lock.layout_id} differs from supported {LAYOUT_ID}")
    return problems


def write_lock(lock: DataLock, path: Path) -> None:
    write_json_atomic(path, lock.to_json())


def read_lock(path: Path) -> DataLock:
    payload = read_json(path)
    if not isinstance(payload, dict):
        raise LockError("data lock must be a JSON object")
    return DataLock.from_json(payload)
