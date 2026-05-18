"""Device selection preview — queries Nautobot for devices matching a filter."""
from __future__ import annotations

import os
from typing import Any

import httpx


class NautobotNotConfiguredError(Exception):
    """Raised when required Nautobot environment variables are missing."""


_DEVICE_QUERY = """
query DevicePreview($filters: [DeviceFilter]) {
  devices(filters: $filters) {
    name
    site { name }
    role { name }
    status { value }
  }
}
"""


def _build_filters(device_filter: dict[str, str]) -> list[dict[str, Any]]:
    """Translate a flat key-value filter dict into Nautobot GraphQL filter objects."""
    filters: list[dict[str, Any]] = []
    for key, value in device_filter.items():
        filters.append({key: {"ic": value}})
    return filters


async def preview_device_selection(
    device_filter: dict[str, str],
) -> list[dict[str, str | None]]:
    """Return devices from Nautobot matching *device_filter*.

    Raises NautobotNotConfiguredError if NAUTOBOT_URL or NAUTOBOT_TOKEN is absent.
    """
    url = os.environ.get("NAUTOBOT_URL", "").rstrip("/")
    token = os.environ.get("NAUTOBOT_TOKEN", "")

    if not url or not token:
        raise NautobotNotConfiguredError(
            "NAUTOBOT_URL and NAUTOBOT_TOKEN environment variables must be set"
        )

    graphql_url = f"{url}/api/graphql/"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "query": _DEVICE_QUERY,
        "variables": {"filters": _build_filters(device_filter)},
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(graphql_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    devices: list[dict[str, str | None]] = []
    for device in data.get("data", {}).get("devices", []):
        devices.append(
            {
                "name": device.get("name"),
                "site": (device.get("site") or {}).get("name"),
                "role": (device.get("role") or {}).get("name"),
                "status": (device.get("status") or {}).get("value"),
            }
        )

    return devices
