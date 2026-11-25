"""The Netmiko device type of a workflow device (W3a-17).

Nine steps used to repeat the same five lines: the device's driver and platform, and the step's
``network_driver_override``. A device the platform map does not know raises
``UnsupportedPlatformError`` (it carries its ``FailureInfo``), so the caller fails that device.
"""

from __future__ import annotations

from models.workflow_context import DeviceContext
from services.network.netmiko.platform import resolve_connection_device_type


def connection_device_type(device: DeviceContext, override: str | None) -> str:
    """The Netmiko ``device_type`` for ``device``; an explicit ``override`` wins."""
    return resolve_connection_device_type(
        network_driver=device.network_driver, platform=device.platform, override=override
    )
