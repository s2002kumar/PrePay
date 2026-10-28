"""Vectorized field-domain validation with the same semantics as :meth:`Field.violation`.

Used by streaming ingest to count violations per field without materializing Python rows.
Parity with the scalar method is property-tested.
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.compute as pc

from prepay.contracts.layout import NUMERIC_PATTERNS, Field, Kind


def _fullmatch(values: pa.Array, pattern: str) -> pa.Array:
    return pc.match_substring_regex(values, pattern=f"^(?:{pattern})$")


def violation_mask(field: Field, values: pa.Array) -> pa.Array:
    """Boolean array: True where a raw string value breaks the field's documented domain."""
    exempt = pc.or_(
        pc.equal(values, ""), pc.is_in(values, value_set=pa.array(field.missing, pa.string()))
    )
    bad = pc.greater(pc.utf8_length(values), field.max_length)
    if field.kind is Kind.CODE:
        bad = pc.or_(bad, pc.invert(pc.is_in(values, value_set=pa.array(field.codes, pa.string()))))
    if field.pattern is not None:
        bad = pc.or_(bad, pc.invert(_fullmatch(values, field.pattern)))
    if field.kind in (Kind.INTEGER, Kind.DECIMAL):
        numeric = _fullmatch(values, NUMERIC_PATTERNS[field.kind])
        bad = pc.or_(bad, pc.invert(numeric))
        if field.value_range is not None:
            low, high = field.value_range
            parsed = pc.cast(pc.if_else(numeric, values, pa.scalar("0")), pa.float64())
            outside = pc.or_(pc.less(parsed, low), pc.greater(parsed, high))
            bad = pc.or_(bad, pc.and_(numeric, outside))
    return pc.and_(pc.invert(exempt), bad)


def count_violations(field: Field, values: pa.Array) -> int:
    return int(pc.sum(pc.cast(violation_mask(field, values), pa.int64())).as_py() or 0)
