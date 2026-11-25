"""Strict parsing of boolean and whole-number configuration values.

Used by the workflow steps (through ``workflow_steps/common/step_flags.py``) and by the workflow
service when it normalises stored node configuration.
"""

from __future__ import annotations

from typing import Any

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off", ""})


def _prefix(step_id: str | None) -> str:
    return f"{step_id}: " if step_id else ""


def parse_bool_flag(
    config: dict[str, Any], key: str, *, default: bool = False, step_id: str | None = None
) -> bool:
    """A boolean config value that may arrive as a bool, a string like ``"false"``, or a number.

    An unrecognised string (a typo such as ``"ture"``) raises instead of silently meaning false.
    ``step_id`` prefixes the error message.
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
    raise ValueError(f"{_prefix(step_id)}{key} must be true or false, got {value!r}")


def parse_int_flag(
    config: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int = 0,
    maximum: int | None = None,
    step_id: str | None = None,
) -> int:
    """A whole-number config value; blank or missing means ``default``.

    ``True``, ``7.9`` and text that is not a whole number raise; ``step_id`` prefixes the message.
    """
    prefix = _prefix(step_id)
    value = config.get(key, default)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{prefix}{key} must be a whole number, got {value!r}")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{prefix}{key} must be a whole number, got {value!r}")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{prefix}{key} must be a whole number, got {value!r}") from exc
    if number < minimum or (maximum is not None and number > maximum):
        upper = maximum if maximum is not None else "unbounded"
        raise ValueError(f"{prefix}{key} must be between {minimum} and {upper}, got {number}")
    return number


def parse_float_flag(
    config: dict[str, Any],
    key: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
    step_id: str | None = None,
) -> float:
    """A number config value in ``[minimum, maximum]``; blank or missing means ``default``.

    ``True``, text that is not a number, ``nan`` and ``inf`` raise; ``step_id`` prefixes the
    message.
    """
    value = config.get(key, default)
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    message = f"{_prefix(step_id)}{key} must be a number between {minimum:g} and {maximum:g}"
    if isinstance(value, bool):
        raise ValueError(f"{message}, got {value!r}")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{message}, got {value!r}") from exc
    if not (minimum <= number <= maximum):  # also false for nan
        raise ValueError(f"{message}, got {value!r}")
    return number
