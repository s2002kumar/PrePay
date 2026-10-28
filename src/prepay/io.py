"""Filesystem helpers: atomic publication of outputs and streaming checksums."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

CHUNK_BYTES = 1 << 20


def sha256_file(path: Path) -> str:
    """Streaming SHA-256 of a file (bounded memory for multi-GB inputs)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


@contextlib.contextmanager
def atomic_path(target: Path) -> Iterator[Path]:
    """Yield a temporary sibling path; on success fsync it and atomically rename onto ``target``.

    On any exception the temporary file is removed and ``target`` is left untouched, so readers
    never observe a partially written output.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        yield tmp
        with tmp.open("rb+") as handle:
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def write_json_atomic(target: Path, payload: Any) -> None:
    """Write canonical (sorted, indented, LF) JSON atomically."""
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with atomic_path(target) as tmp:
        tmp.write_text(text, encoding="utf-8", newline="\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
