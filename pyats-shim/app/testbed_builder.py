"""Builds a pyATS testbed dict from the shim's device request payload."""

from __future__ import annotations

from typing import Any


class TestbedBuildError(ValueError):
    """Raised when a device entry is missing required fields or is malformed."""


def build_testbed_dict(devices: list[dict[str, Any]]) -> dict[str, Any]:
    if not devices:
        raise TestbedBuildError("At least one device is required")

    testbed_devices: dict[str, Any] = {}
    for device in devices:
        name = device.get("name")
        host = device.get("host")
        os_name = device.get("os")
        username = device.get("username")
        password = device.get("password")
        missing = [
            field
            for field, value in (
                ("name", name),
                ("host", host),
                ("os", os_name),
                ("username", username),
            )
            if not value
        ] + (["password"] if password is None else [])
        if missing:
            # Field names only: the entry holds the device password and must never be echoed.
            raise TestbedBuildError(
                f"Device entry is missing required field(s): {', '.join(missing)}"
            )
        if name in testbed_devices:
            raise TestbedBuildError(f"Duplicate device name: {name}")

        connection: dict[str, Any] = {
            "protocol": device.get("protocol", "ssh"),
            "ip": host,
        }
        port = device.get("port")
        if port is not None:
            connection["port"] = port

        testbed_devices[name] = {
            "os": os_name,
            "type": device.get("platform") or os_name,
            "connections": {"cli": connection},
            "credentials": {
                "default": {
                    "username": username,
                    "password": password,
                }
            },
        }

    return {"devices": testbed_devices}
