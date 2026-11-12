"""Run-level message templating shared by notification steps.

Notification steps (``notify-mattermost``, ``send-mail``) send *one* message per
step execution, not one per device. On top of the per-device
``{path.to.value}`` placeholders (see ``placeholder_template``) they support two
run-level placeholders that don't belong to any single device:

* ``{devices}`` -- comma-joined device names
* ``{device_count}`` -- number of devices in context
* ``{run_summary}`` -- one-paragraph outcome overview: counts per device status and the
  names (with error codes, never error text) of failed devices
"""

from __future__ import annotations

import re
from collections import Counter

from models.workflow_context import DeviceStatus, WorkflowContext
from workflow_steps.common.placeholder_template import render_placeholder_template

# Run-level placeholders are swapped for markers first and substituted last, so a device
# named ``{device.hostname}`` or ``{run.id}`` is never evaluated by the per-device pass.
_DEVICES = "\x00devices\x00"
_DEVICE_COUNT = "\x00device_count\x00"
_RUN_SUMMARY = "\x00run_summary\x00"
_MARKER = re.compile("|".join(re.escape(m) for m in (_DEVICES, _DEVICE_COUNT, _RUN_SUMMARY)))


def apply_run_placeholders(message: str, context: WorkflowContext) -> str:
    """Protect ``{devices}`` and ``{device_count}``; :func:`finish_run_placeholders` fills them."""
    del context
    return (
        message.replace("{devices}", _DEVICES)
        .replace("{device_count}", _DEVICE_COUNT)
        .replace("{run_summary}", _RUN_SUMMARY)
    )


def build_run_summary(context: WorkflowContext) -> str:
    """Status counts plus the failed devices (error codes only: messages can echo device output)."""
    devices = list(context.devices.values())
    if not devices:
        return "No devices in this run."
    counts = Counter(device.status for device in devices)
    parts = [
        f"{counts[status]} {status.value}"
        for status in (
            DeviceStatus.OK,
            DeviceStatus.FAILED,
            DeviceStatus.SKIPPED,
            DeviceStatus.PENDING,
        )
        if counts[status]
    ]
    lines = [f"{len(devices)} device(s): {', '.join(parts)}."]
    for device in devices:
        if device.status is not DeviceStatus.FAILED:
            continue
        codes = sorted({error.code for error in device.errors})
        lines.append(f"Failed: {device.name}" + (f" ({', '.join(codes)})" if codes else ""))
    return "\n".join(lines)


def finish_run_placeholders(rendered: str, context: WorkflowContext) -> str:
    """Substitute the protected run-level placeholders against every device in context.

    One pass over the text: a substituted value (a device name, the summary) is never scanned
    again, so a name that contains a marker cannot expand another one.
    """
    values = {
        _DEVICES: ", ".join(device.name.replace("\x00", "") for device in context.devices.values()),
        _DEVICE_COUNT: str(len(context.devices)),
        _RUN_SUMMARY: build_run_summary(context),
    }
    return _MARKER.sub(lambda match: values[match.group(0)], rendered)


def render_for_all_devices(message: str, context: WorkflowContext) -> str | None:
    """Render ``message`` once per device, newline-joined; ``None`` means "nothing to send".

    With no ``{...}`` left after the run-level placeholders the message is
    returned as-is regardless of device count. Otherwise it is device-scoped:
    with no devices to resolve against, return ``None`` so the caller can skip
    instead of sending an unresolved placeholder.
    """
    aggregated = apply_run_placeholders(message, context)
    if "{" not in aggregated:
        return finish_run_placeholders(aggregated, context)

    devices = list(context.devices.values())
    if not devices:
        return None

    return finish_run_placeholders(
        "\n".join(render_placeholder_template(aggregated, device) for device in devices), context
    )


def render_for_first_device(message: str, context: WorkflowContext) -> str | None:
    """Like :func:`render_for_all_devices`, but device placeholders resolve against the
    first device only, producing a single line. Used for single-line values (mail
    subject, addresses) that cannot be newline-joined.
    """
    aggregated = apply_run_placeholders(message, context)
    if "{" not in aggregated:
        return finish_run_placeholders(aggregated, context)

    devices = list(context.devices.values())
    if not devices:
        return None

    return finish_run_placeholders(render_placeholder_template(aggregated, devices[0]), context)
