"""Field type, null share and sample values inferred from a bounded set of recent rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from models.reports import RESERVED_FIELD_NAMES, FieldInfo, FieldType

MAX_SAMPLE_VALUES = 5
MAX_SAMPLE_CHARS = 100


def _value_type(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):  # before int: bool is an int subclass
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def _field_type(seen: set[str]) -> FieldType:
    if not seen:
        return "unknown"
    if len(seen) == 1:
        return next(iter(seen))  # type: ignore[return-value]
    return "mixed"


def infer_fields(rows: Sequence[Mapping[str, Any]], declared: Sequence[str]) -> list[FieldInfo]:
    """One ``FieldInfo`` per declared field (in that order), then any other key seen in *rows*."""
    # Rows written before the reserved names existed may carry such a key; it is not a field.
    names = [name for name in declared if name not in RESERVED_FIELD_NAMES]
    for row in rows:
        for key in row:
            if key not in names and key not in RESERVED_FIELD_NAMES:
                names.append(key)

    fields: list[FieldInfo] = []
    for name in names:
        seen: set[str] = set()
        samples: list[str] = []
        nulls = 0
        for row in rows:
            value = row.get(name)
            kind = _value_type(value)
            if kind is None:
                nulls += 1
                continue
            seen.add(kind)
            text = str(value)[:MAX_SAMPLE_CHARS]
            if len(samples) < MAX_SAMPLE_VALUES and text not in samples:
                samples.append(text)
        fields.append(
            FieldInfo(
                name=name,
                type=_field_type(seen),
                null_share=(nulls / len(rows)) if rows else 0.0,
                sample_values=samples,
            )
        )
    return fields
