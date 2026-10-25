"""Default configuration for the remove-from-nautobot step."""

from __future__ import annotations


def get_config() -> dict:
    return {
        "nautobot_source_id": "",
        "device_id": "{device.id}",
        "remove_ip_addresses": False,
    }
