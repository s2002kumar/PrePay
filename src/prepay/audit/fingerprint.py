"""Order-independent content fingerprints of warehouse tables, to compare two builds.

``sum(hash(row)) mod 2^64`` over every row is insensitive to physical row order but changes
when any value in any row changes. It holds no data values, only a count and a 64-bit sum.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from prepay.transform import warehouse_path


def warehouse_fingerprint(data_root: Path) -> dict[str, dict[str, Any]]:
    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
        tables = [
            r[0]
            for r in con.sql(
                "select table_name from information_schema.tables "
                "where table_type = 'BASE TABLE' order by table_name"
            ).fetchall()
        ]
        out = {}
        for table in tables:
            rows, digest = con.sql(
                f"select count(*), sum(hash(t)::hugeint) % 18446744073709551616 "  # noqa: S608
                f'from "{table}" as t'
            ).fetchall()[0]
            out[table] = {"rows": int(rows), "fingerprint": str(digest)}
    return out
