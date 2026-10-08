"""Run-level message templating shared by notification steps.

Notification steps (``notify-mattermost``, ``send-mail``) send *one* message per
step execution, not one per device. On top of the per-device
``{path.to.value}`` placeholders (see ``placeholder_template``) they support two
run-level placeholders that don't belong to any single device:

* ``{devices}`` -- comma-joined device names
* ``{device_count}`` -- number of devices in context
"""

from __future__ import annotations

from models.workflow_context import WorkflowContext
from workflow_steps.common.placeholder_template import render_placeholder_template


def apply_run_placeholders(message: str, context: WorkflowContext) -> str:
    """Resolve ``{devices}`` and ``{device_count}`` against every device in context."""
    devices = list(context.devices.values())
    device_names = ", ".join(device.name for device in devices)
    return message.replace("{devices}", device_names).replace("{device_count}", str(len(devices)))


def render_for_all_devices(message: str, context: WorkflowContext) -> str | None:
    """Render ``message`` once per device, newline-joined; ``None`` means "nothing to send".

    With no ``{...}`` left after the run-level placeholders the message is
    returned as-is regardless of device count. Otherwise it is device-scoped:
    with no devices to resolve against, return ``None`` so the caller can skip
    instead of sending an unresolved placeholder.
    """
    aggregated = apply_run_placeholders(message, context)
    if "{" not in aggregated:
        return aggregated

    devices = list(context.devices.values())
    if not devices:
        return None

    return "\n".join(render_placeholder_template(aggregated, device) for device in devices)


def render_for_first_device(message: str, context: WorkflowContext) -> str | None:
    """Like :func:`render_for_all_devices`, but device placeholders resolve against the
    first device only, producing a single line. Used for single-line values (mail
    subject, addresses) that cannot be newline-joined.
    """
    aggregated = apply_run_placeholders(message, context)
    if "{" not in aggregated:
        return aggregated

    devices = list(context.devices.values())
    if not devices:
        return None

    return render_placeholder_template(aggregated, devices[0])
