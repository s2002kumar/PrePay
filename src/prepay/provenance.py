"""Reproducibility digests shared by benchmarks, model runs and seals."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from prepay.features.spec import FEATURES

REPO_ROOT = Path(__file__).resolve().parents[2]


def canonical_digest(payload: Any) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def git_sha() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        out = subprocess.run(  # noqa: S603 - resolved git binary, fixed arguments
            [git, "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def software_lock_digest() -> str | None:
    lock = REPO_ROOT / "uv.lock"
    return hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else None


def feature_contract_digest() -> str:
    return canonical_digest([(f.name, f.kind, f.source) for f in FEATURES])


def tree_digest(root: Path, *, exclude: tuple[str, ...] = ()) -> str:
    """Digest over every file under ``root`` (relative path + content hash), sorted."""
    entries = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if any(relative == e or relative.startswith(f"{e}/") for e in exclude):
            continue
        entries.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return canonical_digest(entries)
