"""Strict parsing of boolean and whole-number configuration values.

Used by the workflow steps (through ``workflow_steps/common/step_flags.py``) and by the workflow
service when it normalises stored node configuration.
"""

from __future__ import annotations

from typing import Any

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off", ""})


def parse_bool_flag(config: dict[str, Any], key: str, *, default: bool = False) -> bool:
    """A boolean config value that may arrive as a bool, a string like ``"false"``, or a number.

    An unrecognised string (a typo such as ``"ture"``) raises instead of silently meaning false.
    """
    value = config.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    raise ValueError(f"{key} must be true or false, got {value!r}")


def parse_int_flag(
    config: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    """A whole-number config value; blank or missing means ``default``."""
    value = config.get(key, default)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a whole number, got {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{key} must be a whole number, got {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be a whole number, got {value!r}") from exc
    if number < minimum or (maximum is not None and number > maximum):
        upper = maximum if maximum is not None else "unbounded"
        raise ValueError(f"{key} must be between {minimum} and {upper}, got {number}")
    return number
