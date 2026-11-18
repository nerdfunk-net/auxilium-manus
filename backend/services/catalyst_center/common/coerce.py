"""Lenient scalar coercion for Catalyst Center payloads.

The controller is loose with types (numbers arrive as strings, empty strings stand for
"unset"), so normalization maps anything unusable to ``None`` instead of failing.
"""

from __future__ import annotations

import math
from typing import Any


def text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    result = str(value).strip()
    return result or None


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except TypeError, ValueError:
        return None
    return result if math.isfinite(result) else None  # NaN / Infinity are not data


def integer(value: Any) -> int | None:
    parsed = number(value)
    # A fractional count is not a count: skip it rather than store it truncated.
    return int(parsed) if parsed is not None and parsed.is_integer() else None


def boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    return None
