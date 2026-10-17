"""Device health from Cisco Catalyst Center: ``GET /device-detail`` (read-only).

Verified on the DevNet sandbox with ``identifier=uuid&searchBy=<device uuid>``. Numbers such as
``cpu`` and ``memory`` arrive as strings. ``GET /device-health`` is a bulk alternative that is
not used here.
"""

from __future__ import annotations

from typing import Any

from models.catalyst_center_facts import CatalystCenterHealth
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.coerce import boolean, integer, number, text
from services.catalyst_center.common.exceptions import CatalystCenterAPIError
from services.catalyst_center.common.ids import safe_device_id
from services.catalyst_center.credentials import CatalystCenterCredentials

DEVICE_DETAIL_PATH = "/dna/intent/api/v1/device-detail"


class CatalystCenterHealthService:
    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials

    async def get_device_health(self, device_id: str) -> CatalystCenterHealth:
        payload: Any = await self._client.request(
            self._credentials,
            "GET",
            DEVICE_DETAIL_PATH,
            params={"identifier": "uuid", "searchBy": safe_device_id(device_id)},
        )
        body = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(body, dict) or not body:
            raise CatalystCenterAPIError("Catalyst Center returned no health data for the device")
        return CatalystCenterHealth(
            overall_health=number(body.get("overallHealth")),
            cpu=number(body.get("cpu")),
            cpu_score=number(body.get("cpuScore")),
            memory=number(body.get("memory")),
            memory_score=number(body.get("memoryScore")),
            communication_state=text(body.get("communicationState")),
            collection_status=text(body.get("collectionStatus")),
            ha_status=text(body.get("haStatus")),
            stack_type=text(body.get("stackType")),
            ring_status=boolean(body.get("ringStatus")),
            maintenance_mode=boolean(body.get("maintenanceMode")),
            last_boot_time=integer(body.get("lastBootTime")),
            timestamp=integer(body.get("timestamp")),
            os_type=text(body.get("osType")),
            software_version=text(body.get("softwareVersion")),
            role=text(body.get("nwDeviceRole")),
        )
