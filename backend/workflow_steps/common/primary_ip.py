"""A device's primary IPv4 as the ISE steps read it."""

from __future__ import annotations

from models.workflow_context import DeviceContext
from services.workflow_context.attribute_path import resolve_device_value


def effective_primary_ip4(device: DeviceContext) -> str | None:
    """The top-level ``primary_ip4`` (set by Get from Nautobot / Get from Git), else the
    ``nautobot`` attribute bag.

    The bag is the only place the address lives when a device came from Get from List or
    Get from ISE and was later enriched by a Get Nautobot Attributes step.
    """
    if device.primary_ip4:
        return device.primary_ip4
    value = resolve_device_value(device, "nautobot.primary_ip4.address")
    return str(value) if value else None
