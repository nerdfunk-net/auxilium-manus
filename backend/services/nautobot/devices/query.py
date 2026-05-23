"""Device GraphQL queries against Nautobot."""

from __future__ import annotations

import logging

from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)

DEVICE_CACHE_TTL = 30 * 60  # default 30 minutes

DEVICE_DETAILS_QUERY = """
query DeviceDetails($deviceId: ID!) {
    device(id: $deviceId) {
        id
        name
        serial
        _custom_field_data
        primary_ip4 { id address }
        role { id name }
        device_type { id model manufacturer { id name } }
        platform { id name }
        location { id name parent { id name } }
        status { id name }
        tags { id name color }
        interfaces {
            id name type enabled mtu mac_address description
            status { id name }
            ip_addresses { id address ip_version status { id name } }
        }
    }
}
"""


class DeviceQueryService:
    def __init__(
        self,
        nautobot: NautobotService,
        credentials: NautobotCredentials,
        cache_service=None,
        device_ttl: int = DEVICE_CACHE_TTL,
    ) -> None:
        self._nautobot = nautobot
        self._credentials = credentials
        self._cache = cache_service
        self._cache_scope = credentials.cache_scope
        self._device_ttl = device_ttl

    def _details_cache_key(self, device_id: str) -> str:
        return f"nautobot:device_details:{self._cache_scope}:{device_id}"

    async def get_device_details(self, device_id: str, use_cache: bool = True) -> dict:
        cache_key = self._details_cache_key(device_id)
        if use_cache and self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached

        result = await self._nautobot.graphql_query(
            DEVICE_DETAILS_QUERY,
            {"deviceId": device_id},
            self._credentials,
        )
        if "errors" in result:
            raise ValueError(f"GraphQL errors: {result['errors']}")

        device = (result.get("data") or {}).get("device")
        if not device:
            raise ValueError(f"Device {device_id} not found in Nautobot")

        if self._cache is not None:
            self._cache.set(cache_key, device, self._device_ttl)
        return device
