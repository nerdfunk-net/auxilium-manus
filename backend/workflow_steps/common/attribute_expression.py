"""Resolve a generic ``{path}`` / ``{path | default('x')}`` value expression.

Unlike ``update_field_expression.py`` (Nautobot-device-field specific, with a
``nautobot.origin`` special case), this is for arbitrary named values — e.g. a Nautobot
job's parameters — where the field name carries no special meaning of its own.
"""

from __future__ import annotations

import re
from typing import Any

from models.workflow_context import DeviceContext
from services.workflow_context.attribute_path import resolve_device_attribute, resolve_device_value

_BRACE_EXPRESSION = re.compile(
    r"^\{\s*"
    r"(?P<path>[^}|]+?)"
    r"(?:\s*\|\s*default\(\s*(?P<quote>['\"])(?P<default>.*?)(?P=quote)\s*\))?"
    r"\s*\}$"
)


def _stringify_resolved(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def resolve_attribute_expression(
    device: DeviceContext,
    raw_value: str,
    *,
    run_id: str | None = None,
    reveal_secrets: bool = True,
) -> str | None:
    """Resolve one parameter value expression for one device.

    A plain string (no ``{...}`` wrapper) is returned as-is (a literal). A ``{path}``
    expression resolves against the device's scalars/attribute bags, falling back to the
    optional ``| default('...')`` clause when the path has no value.
    """
    expression = raw_value.strip()
    if not expression:
        return None

    match = _BRACE_EXPRESSION.match(expression)
    if not match:
        return expression

    path = match.group("path").strip()
    default_value = match.group("default")

    resolved = resolve_device_attribute(device, path, reveal_secrets=reveal_secrets)
    if resolved is None:
        resolved = _stringify_resolved(resolve_device_value(device, path, run_id=run_id))

    if resolved is not None:
        return resolved
    if default_value is not None:
        return default_value
    return None
