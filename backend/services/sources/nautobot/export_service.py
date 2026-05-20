"""Analysis helpers for resolved Nautobot device sets."""

from __future__ import annotations

import logging
from typing import Any

from models.sources_nautobot import DeviceInfo
from services.nautobot.devices.query import DeviceQueryService

logger = logging.getLogger(__name__)


class NautobotSourceExportService:
    def __init__(self, device_query_service: DeviceQueryService | None = None) -> None:
        self._device_query_service = device_query_service

    async def analyze_devices(self, devices: list[DeviceInfo]) -> dict[str, Any]:
        if not devices:
            return {
                "locations": [],
                "tags": [],
                "custom_fields": {},
                "statuses": [],
                "roles": [],
                "device_count": 0,
            }

        if self._device_query_service is None:
            raise RuntimeError("DeviceQueryService is required for analyze_devices")

        locations: set[str] = set()
        tags: set[str] = set()
        custom_fields: dict[str, set[str]] = {}
        statuses: set[str] = set()
        roles: set[str] = set()

        for device in devices:
            try:
                detail = await self._device_query_service.get_device_details(
                    device.id,
                    use_cache=True,
                )
                location = detail.get("location") or {}
                location_name = location.get("name") if isinstance(location, dict) else None
                if location_name:
                    locations.add(location_name)

                for tag in detail.get("tags") or []:
                    if isinstance(tag, dict) and tag.get("name"):
                        tags.add(tag["name"])

                for field_key, field_value in (detail.get("_custom_field_data") or {}).items():
                    if field_value is None:
                        continue
                    custom_fields.setdefault(field_key, set())
                    if isinstance(field_value, list):
                        custom_fields[field_key].update(str(v) for v in field_value if v)
                    else:
                        custom_fields[field_key].add(str(field_value))

                status = detail.get("status") or {}
                if isinstance(status, dict) and status.get("name"):
                    statuses.add(status["name"])

                role = detail.get("role") or {}
                if isinstance(role, dict) and role.get("name"):
                    roles.add(role["name"])
            except Exception as exc:
                logger.error(
                    "Error analyzing device %s (%s): %s",
                    device.name,
                    device.id,
                    exc,
                )

        return {
            "locations": sorted(locations),
            "tags": sorted(tags),
            "custom_fields": {key: sorted(values) for key, values in custom_fields.items()},
            "statuses": sorted(statuses),
            "roles": sorted(roles),
            "device_count": len(devices),
        }
