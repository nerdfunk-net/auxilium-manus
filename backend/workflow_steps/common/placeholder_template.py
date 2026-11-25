"""Shared ``{path.to.attribute}`` placeholder substitution for step config strings."""

from __future__ import annotations

from collections.abc import Callable

from models.workflow_context import DeviceContext, DeviceError
from services.workflow_context.attribute_path import resolve_device_attribute
from workflow_steps.common.placeholder_scan import is_path_shaped, next_placeholder


def render_placeholder_template(
    template: str,
    device: DeviceContext,
    *,
    value_transform: Callable[[str], str] | None = None,
    error: DeviceError | None = None,
) -> str:
    """Replace ``{path.to.value}`` placeholders with the device's resolved
    attribute values. A path that resolves to nothing renders as an empty
    string rather than failing the step.

    Callers that splice the rendered result into something with its own
    syntax (e.g. a regular expression) should pass ``value_transform`` (e.g.
    ``re.escape``) so a resolved value can't be misinterpreted as syntax in
    that context.

    Pass ``error`` (one entry from ``device.errors``) to also resolve
    ``{error.step_id}``, ``{error.node_id}``, ``{error.code}``,
    ``{error.message}`` — used by steps reporting on a specific accumulated
    error (e.g. ``notify-on-error``) rather than device state.

    ``reveal_secrets=False`` is always used here: this helper is for
    generic/bulk steps that copy a resolved value into a new location (a log
    message, a search pattern) rather than consuming it in-memory for one
    trusted call — see the secret-valued attributes rules in
    doc/WORKFLOW-STEPS.md.
    """

    pieces: list[str] = []
    cursor = 0  # text before this index is already in ``pieces``
    scan = 0  # where the next candidate is looked for
    while (span := next_placeholder(template, scan)) is not None:
        opening, closing = span
        inner = template[opening + 1 : closing]
        if not is_path_shaped(inner):
            scan = opening + 1  # text in braces: leave it, look for a path after the brace
            continue
        value = resolve_device_attribute(device, inner, reveal_secrets=False, error=error)
        # NUL delimits the run-level markers of run_message_template; a resolved value must never
        # carry one in, or it would be expanded as a run-level placeholder.
        text = value.replace("\x00", "") if value is not None else ""
        pieces.append(template[cursor:opening])
        pieces.append(value_transform(text) if value_transform else text)
        cursor = scan = closing + 1
    pieces.append(template[cursor:])
    return "".join(pieces)
