"""One accessor for the scalar fields of a device (C6-02).

``device.primary_ip4`` is the bare address everywhere (attribute paths, ``{placeholders}`` and
Jinja); the stored form with the prefix length stays reachable as ``device.primary_ip4_cidr``.
"""

from __future__ import annotations

from typing import Any

from models.workflow_context import DeviceContext


def device_scalar(device: DeviceContext, name: str) -> Any:
    if name == "primary_ip4":
        return device.primary_ip4.split("/")[0] if device.primary_ip4 else None
    if name == "primary_ip4_cidr":
        return device.primary_ip4  # as stored, with the mask
    return getattr(device, name)
