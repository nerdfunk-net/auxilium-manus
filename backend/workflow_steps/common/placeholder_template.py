"""Shared ``{path.to.attribute}`` placeholder substitution for step config strings."""

from __future__ import annotations

import re
from collections.abc import Callable

from models.workflow_context import DeviceContext
from workflow_steps.common.attribute_path import resolve_device_attribute

_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z0-9_.]+)\}")


def render_placeholder_template(
    template: str,
    device: DeviceContext,
    *,
    value_transform: Callable[[str], str] | None = None,
) -> str:
    """Replace ``{path.to.value}`` placeholders with the device's resolved
    attribute values. A path that resolves to nothing renders as an empty
    string rather than failing the step.

    Callers that splice the rendered result into something with its own
    syntax (e.g. a regular expression) should pass ``value_transform`` (e.g.
    ``re.escape``) so a resolved value can't be misinterpreted as syntax in
    that context.

    ``reveal_secrets=False`` is always used here: this helper is for
    generic/bulk steps that copy a resolved value into a new location (a log
    message, a search pattern) rather than consuming it in-memory for one
    trusted call — see the secret-valued attributes rules in
    doc/WORKFLOW-STEPS.md.
    """

    def _replace(match: re.Match[str]) -> str:
        value = resolve_device_attribute(device, match.group(1), reveal_secrets=False)
        text = value if value is not None else ""
        return value_transform(text) if value_transform else text

    return _PLACEHOLDER_PATTERN.sub(_replace, template)
