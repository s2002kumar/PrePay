"""MODELING §5 time windows and the holdout access guard.

Windows split by the *target month* of a prediction, never by row or loan. Test windows can only
be read with a verified seal (see :mod:`prepay.modeling.lockbox`): training, tuning, calibration
and selection code cannot open them by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import duckdb

from prepay import periods
from prepay.features.panel import PanelBatch, read_panel

if TYPE_CHECKING:
    from prepay.modeling.lockbox import Seal

Role = Literal["train", "validation", "test"]


class HoldoutAccessError(PermissionError):
    """Something other than the sealed lockbox evaluation tried to read a test window."""


@dataclass(frozen=True, slots=True)
class Window:
    name: str
    role: Role
    first: int  # month index, inclusive
    last: int  # month index, inclusive

    @property
    def label(self) -> str:
        return f"{periods.to_iso(self.first)}..{periods.to_iso(self.last)}"


def standard_windows(cutoff_month: int) -> tuple[Window, ...]:
    """Train through 2017-12; validation A 2018, B 2019; tests 2020-21, 2022-23, 2024-cutoff."""
    m = periods.month
    return (
        Window("train", "train", 0, m(2017, 12)),
        Window("validation_a", "validation", m(2018, 1), m(2018, 12)),
        Window("validation_b", "validation", m(2019, 1), m(2019, 12)),
        Window("test_a", "test", m(2020, 1), m(2021, 12)),
        Window("test_b", "test", m(2022, 1), m(2023, 12)),
        Window("test_c", "test", m(2024, 1), cutoff_month),
    )


def window(name: str, cutoff_month: int) -> Window:
    for w in standard_windows(cutoff_month):
        if w.name == name:
            return w
    raise KeyError(name)


def read_window(
    con: duckdb.DuckDBPyConnection,
    w: Window,
    *,
    sample_fraction: float | None = None,
    seal: Seal | None = None,
) -> PanelBatch:
    """Read a window's panel rows; test windows require a verified seal."""
    if w.role == "test":
        if seal is None:
            raise HoldoutAccessError(
                f"{w.name} is a sealed holdout; only `prepay evaluate-lockbox` may read it"
            )
        seal.verify()
    return read_panel(con, w.first, w.last, sample_fraction=sample_fraction)
