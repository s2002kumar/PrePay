"""Atomic publication of outputs."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from prepay.io import atomic_path, read_json, write_json_atomic


def test_atomic_write_replaces_target_only_on_success(tmp_path: Path) -> None:
    target = tmp_path / "out.json"
    write_json_atomic(target, {"a": 1})

    def crash_mid_write() -> None:
        with atomic_path(target) as tmp:
            tmp.write_text("partial")
            raise RuntimeError("crash mid-write")

    with pytest.raises(RuntimeError):
        crash_mid_write()
    assert read_json(target) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_atomic_outputs_are_readable_by_other_users(tmp_path: Path) -> None:
    previous = os.umask(0o022)
    try:
        write_json_atomic(tmp_path / "manifest.json", {"ok": True})
    finally:
        os.umask(previous)
    mode = stat.S_IMODE((tmp_path / "manifest.json").stat().st_mode)
    assert mode == 0o644  # mkstemp alone would leave 0600 (unreadable by a runtime user)
