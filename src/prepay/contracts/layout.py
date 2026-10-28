"""Typed, fingerprinted descriptions of headerless delimited source files.

A :class:`Layout` is the single source of truth for a file's column positions, canonical column
names, value domains and missing-value sentinels. Ingest uses it to name and validate raw columns;
the dbt staging models and the synthetic generator are tested for parity against it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum


class Kind(StrEnum):
    """Semantic type used when a raw string field is typed in the silver layer."""

    INTEGER = "integer"
    DECIMAL = "decimal"
    MONTH = "month"  # YYYYMM calendar month
    CODE = "code"  # value from a closed enumeration
    IDENTIFIER = "identifier"
    TEXT = "text"


#: Plain decimal notation only: no exponent, whitespace, sign prefix "+", or thousands separators.
NUMERIC_PATTERNS = {Kind.INTEGER: r"-?\d+", Kind.DECIMAL: r"-?\d+(\.\d+)?"}


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """An official document a layout was transcribed from, pinned by content hash."""

    title: str
    url: str
    sha256: str
    retrieved: str  # ISO date the bytes were fetched


@dataclass(frozen=True, slots=True)
class Field:
    """One column of a headerless source file.

    Attributes:
        position: 1-based column position in the file.
        name: canonical snake_case column name used downstream.
        header: the official header text for this position.
        kind: semantic type for typing in the silver layer.
        max_length: maximum field length stated by the official layout.
        codes: closed set of allowed non-missing values for CODE fields (empty otherwise).
        missing: sentinel strings meaning "not available"; mapped to NULL plus a flag downstream.
            An empty string is always treated as missing and need not be listed.
        pattern: optional regular expression every non-missing value must match.
        value_range: optional inclusive numeric range for non-missing INTEGER/DECIMAL values.
    """

    position: int
    name: str
    header: str
    kind: Kind
    max_length: int
    codes: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    pattern: str | None = None
    value_range: tuple[float, float] | None = None

    def violation(self, raw: str) -> str | None:
        """Return why ``raw`` breaks this field's documented domain, or ``None`` if it is valid."""
        if raw == "" or raw in self.missing:
            return None
        if len(raw) > self.max_length:
            return f"length {len(raw)} exceeds documented maximum {self.max_length}"
        if self.kind is Kind.CODE and raw not in self.codes:
            return "value is not in the documented enumeration"
        if self.pattern is not None and re.fullmatch(self.pattern, raw, re.ASCII) is None:
            return "value does not match the documented format"
        if self.kind in (Kind.INTEGER, Kind.DECIMAL):
            if re.fullmatch(NUMERIC_PATTERNS[self.kind], raw, re.ASCII) is None:
                return "value is not numeric"
            number = float(raw)
            if self.value_range is not None:
                low, high = self.value_range
                if not low <= number <= high:
                    return f"value outside documented range [{low:g}, {high:g}]"
        return None


@dataclass(frozen=True, slots=True)
class Layout:
    """A versioned headerless file layout."""

    layout_id: str
    file_kind: str
    delimiter: str
    fields: tuple[Field, ...]
    sources: tuple[SourceDocument, ...] = field(default=())

    def __post_init__(self) -> None:
        positions = [f.position for f in self.fields]
        if positions != list(range(1, len(self.fields) + 1)):
            raise ValueError(f"{self.layout_id}/{self.file_kind}: positions must be 1..n in order")
        names = [f.name for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError(f"{self.layout_id}/{self.file_kind}: duplicate column names")

    @property
    def width(self) -> int:
        return len(self.fields)

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    def field(self, name: str) -> Field:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    def fingerprint(self) -> str:
        """SHA-256 of the layout's structural content (positions, names, types, domains).

        Recorded in every manifest so downstream artifacts are tied to the exact schema used.
        Source-document citations are deliberately excluded: re-downloading an identical layout
        must not change the fingerprint.
        """
        canonical = {
            "layout_id": self.layout_id,
            "file_kind": self.file_kind,
            "delimiter": self.delimiter,
            "fields": [
                {
                    "position": f.position,
                    "name": f.name,
                    "header": f.header,
                    "kind": f.kind.value,
                    "max_length": f.max_length,
                    "codes": list(f.codes),
                    "missing": list(f.missing),
                    "pattern": f.pattern,
                    "value_range": list(f.value_range) if f.value_range else None,
                }
                for f in self.fields
            ],
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()
