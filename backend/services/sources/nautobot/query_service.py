"""
Inventory query service — Nautobot GraphQL query methods for device lookups.

Extracted from InventoryService as part of Phase 4 decomposition.
See: doc/refactoring/REFACTORING_SERVICES.md — Phase 4

Cache strategy (Option A — cache-first):
  Most filter operations load the full device list once from Redis
  (key: nautobot:devices:all, populated by cache_all_devices_task) and
  perform in-Python filtering.  The result is held in self._devices_cache
  for the lifetime of the service instance so that multiple conditions in
  the same inventory preview only pay the Redis round-trip once.

  Exceptions that still go directly to Nautobot GraphQL:
    • location       — Nautobot resolves child-location hierarchy server-side
    • ip_prefix      — requires server-side CIDR containment logic
    • primary_prefix — requires server-side CIDR containment logic, restricted
                        to each device's primary_ip4
    • custom_field   — fields are dynamic and not stored in the cache
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from models.sources_nautobot import DeviceInfo

from services.sources.nautobot.live_query_mixin import NautobotLiveQueryMixin

if TYPE_CHECKING:
    from services.cache.redis_cache_service import RedisCacheService
    from services.nautobot.client import NautobotService
    from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)

_BULK_CACHE_KEY_PREFIX = "nautobot:devices:all"


class NautobotSourceQueryService(NautobotLiveQueryMixin):
    """Handles all Nautobot GraphQL queries for inventory device lookups."""

    def __init__(
        self,
        nautobot: NautobotService,
        credentials: NautobotCredentials,
        cache_service: RedisCacheService | None = None,
    ):

        self._nautobot = nautobot
        self._credentials = credentials
        self._cache_service = cache_service
        self._bulk_cache_key = f"{_BULK_CACHE_KEY_PREFIX}:{credentials.cache_scope}"
        self._devices_cache: list[DeviceInfo] | None = None
        self._custom_field_types_cache: dict[str, str] | None = None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _parse_device_from_cache(self, raw: dict[str, Any]) -> DeviceInfo:
        """Convert a flat cache dict (from extract_device_essentials) to DeviceInfo."""
        tags = raw.get("tags") or []
        return DeviceInfo(
            id=raw.get("id", ""),
            name=raw.get("name"),
            serial=raw.get("serial"),
            primary_ip4=raw.get("primary_ip4"),
            status=raw.get("status"),
            device_type=raw.get("device_type"),
            role=raw.get("role"),
            location=raw.get("location"),
            platform=raw.get("platform"),
            platform_network_driver=raw.get("platform_network_driver"),
            tags=tags,
            manufacturer=raw.get("manufacturer"),
        )

    async def _get_all_devices_cached(self) -> list[DeviceInfo]:
        """
        Return all devices, preferring the Redis bulk cache over a live API call.

        The parsed list is stored in self._devices_cache so subsequent calls
        within the same request pay no extra cost.
        """
        if self._devices_cache is not None:
            return self._devices_cache

        if self._cache_service is not None:
            try:
                raw_list = self._cache_service.get(self._bulk_cache_key)
                if raw_list:
                    devices = [self._parse_device_from_cache(d) for d in raw_list]
                    logger.info(
                        "Cache hit for '%s': %s devices", self._bulk_cache_key, len(devices)
                    )
                    self._devices_cache = devices
                    return devices
                logger.info(
                    "Cache miss for '%s', falling back to Nautobot API", self._bulk_cache_key
                )
            except Exception as exc:
                logger.warning(
                    "Redis read failed for '%s', falling back to Nautobot API: %s",
                    self._bulk_cache_key,
                    exc,
                )

        devices = await self._query_all_devices_live()
        self._devices_cache = devices
        return devices

    # ------------------------------------------------------------------
    # Custom field metadata
    # ------------------------------------------------------------------

    async def _get_custom_field_types(self) -> dict[str, str]:
        """
        Fetch custom field types from Nautobot API and cache them.

        Returns:
            Dictionary mapping custom field keys to their types
            (e.g., {"checkmk_site": "select", "freifeld": "text"})
        """
        if self._custom_field_types_cache is not None:
            return self._custom_field_types_cache

        try:
            from services.nautobot.metadata_service import NautobotMetadataService

            metadata = NautobotMetadataService(self._nautobot, self._credentials)
            logger.info("Fetching custom field types from Nautobot")
            custom_fields = await metadata.get_device_custom_fields()

            type_mapping = {}
            for field in custom_fields:
                field_key = field.get("key")
                field_type_dict = field.get("type", {})
                field_type_value = (
                    field_type_dict.get("value") if isinstance(field_type_dict, dict) else None
                )

                if field_key and field_type_value:
                    type_mapping[field_key] = field_type_value
                    logger.info("Custom field '%s' has type '%s'", field_key, field_type_value)

            logger.info("Loaded %s custom field types: %s", len(type_mapping), type_mapping)

            self._custom_field_types_cache = type_mapping
            return type_mapping

        except Exception as e:
            logger.error("Error fetching custom field types: %s", e, exc_info=True)
            return {}

    # ------------------------------------------------------------------
    # Live Nautobot GraphQL helpers (used as fallback or for uncacheable queries)
    # ------------------------------------------------------------------

    async def _query_all_devices_live(self) -> list[DeviceInfo]:
        """Query all devices from Nautobot without any filters (no cache)."""
        query = """
        query all_devices {
            devices {
                id
                name
                serial
                primary_ip4 {
                    address
                }
                status {
                    name
                }
                device_type {
                    model
                    manufacturer {
                        name
                    }
                }
                role {
                    name
                }
                location {
                    name
                }
                tags {
                    name
                }
                platform {
                    name
                    network_driver
                }
            }
        }
        """

        result = await self._nautobot.graphql_query(query, {}, self._credentials)
        devices_data = result.get("data", {}).get("devices", [])
        logger.info("Retrieved %s total devices from Nautobot", len(devices_data))
        return self._parse_device_data(devices_data)

    async def _query_all_devices(self) -> list[DeviceInfo]:
        """Return all devices, using the bulk cache when available."""
        return await self._get_all_devices_cached()

    # ------------------------------------------------------------------
    # Cache-first query methods
    # ------------------------------------------------------------------

    async def _query_devices_by_name(
        self, name_filter: str, use_contains: bool = False
    ) -> list[DeviceInfo]:
        """Filter devices by name using the bulk cache."""
        if not name_filter or name_filter.strip() == "":
            logger.warning("Empty name_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()

        if use_contains:
            needle = name_filter.lower()
            result = [d for d in all_devices if d.name and needle in d.name.lower()]
        else:
            result = [d for d in all_devices if d.name == name_filter]

        logger.info(
            "Cache filter name='%s' (contains=%s): %s devices",
            name_filter,
            use_contains,
            len(result),
        )
        return result

    async def _query_devices_by_role(
        self, role_filter: str, use_negation: bool = False
    ) -> list[DeviceInfo]:
        """Filter devices by role using the bulk cache."""
        if not role_filter or role_filter.strip() == "":
            logger.warning("Empty role_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()

        if use_negation:
            result = [d for d in all_devices if d.role != role_filter]
        else:
            result = [d for d in all_devices if d.role == role_filter]

        logger.info(
            "Cache filter role='%s' (negation=%s): %s devices",
            role_filter,
            use_negation,
            len(result),
        )
        return result

    async def _query_devices_by_status(self, status_filter: str) -> list[DeviceInfo]:
        """Filter devices by status using the bulk cache."""
        if not status_filter or status_filter.strip() == "":
            logger.warning("Empty status_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()
        result = [d for d in all_devices if d.status == status_filter]
        logger.info("Cache filter status='%s': %s devices", status_filter, len(result))
        return result

    async def _query_devices_by_tag(self, tag_filter: str) -> list[DeviceInfo]:
        """Filter devices by tag using the bulk cache."""
        if not tag_filter or tag_filter.strip() == "":
            logger.warning("Empty tag_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()
        result = [d for d in all_devices if tag_filter in (d.tags or [])]
        logger.info("Cache filter tag='%s': %s devices", tag_filter, len(result))
        return result

    async def _query_devices_by_devicetype(
        self, devicetype_filter: str, use_negation: bool = False
    ) -> list[DeviceInfo]:
        """Filter devices by device type using the bulk cache."""
        if not devicetype_filter or devicetype_filter.strip() == "":
            logger.warning("Empty devicetype_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()

        if use_negation:
            result = [d for d in all_devices if d.device_type != devicetype_filter]
        else:
            result = [d for d in all_devices if d.device_type == devicetype_filter]

        logger.info(
            "Cache filter device_type='%s' (negation=%s): %s devices",
            devicetype_filter,
            use_negation,
            len(result),
        )
        return result

    async def _query_devices_by_manufacturer(
        self, manufacturer_filter: str, use_negation: bool = False
    ) -> list[DeviceInfo]:
        """Filter devices by manufacturer using the bulk cache."""
        if not manufacturer_filter or manufacturer_filter.strip() == "":
            logger.warning("Empty manufacturer_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()

        if use_negation:
            result = [d for d in all_devices if d.manufacturer != manufacturer_filter]
        else:
            result = [d for d in all_devices if d.manufacturer == manufacturer_filter]

        logger.info(
            "Cache filter manufacturer='%s' (negation=%s): %s devices",
            manufacturer_filter,
            use_negation,
            len(result),
        )
        return result

    async def _query_devices_by_platform(self, platform_filter: str) -> list[DeviceInfo]:
        """Filter devices by platform using the bulk cache."""
        if not platform_filter or platform_filter.strip() == "":
            logger.warning("Empty platform_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()
        result = [d for d in all_devices if d.platform == platform_filter]
        logger.info("Cache filter platform='%s': %s devices", platform_filter, len(result))
        return result

    async def _query_devices_by_has_primary(self, has_primary_filter: str) -> list[DeviceInfo]:
        """Filter devices by whether they have a primary IP using the bulk cache."""
        has_primary_bool = has_primary_filter.lower() == "true"

        all_devices = await self._get_all_devices_cached()

        if has_primary_bool:
            result = [d for d in all_devices if d.primary_ip4]
        else:
            result = [d for d in all_devices if not d.primary_ip4]

        logger.info("Cache filter has_primary=%s: %s devices", has_primary_bool, len(result))
        return result

    # ------------------------------------------------------------------
    # Shared parser
    # ------------------------------------------------------------------

    def _parse_device_data(self, devices_data: list[dict[str, Any]]) -> list[DeviceInfo]:
        """Parse GraphQL device data (nested dicts) into DeviceInfo objects."""
        devices = []

        for device_data in devices_data:
            primary_ip = None
            if device_data.get("primary_ip4") and device_data["primary_ip4"].get("address"):
                primary_ip = device_data["primary_ip4"]["address"]

            status = None
            if device_data.get("status") and device_data["status"].get("name"):
                status = device_data["status"]["name"]

            device_type = None
            if device_data.get("device_type") and device_data["device_type"].get("model"):
                device_type = device_data["device_type"]["model"]

            manufacturer = None
            if (
                device_data.get("device_type")
                and device_data["device_type"].get("manufacturer")
                and device_data["device_type"]["manufacturer"].get("name")
            ):
                manufacturer = device_data["device_type"]["manufacturer"]["name"]

            role = None
            if device_data.get("role") and device_data["role"].get("name"):
                role = device_data["role"]["name"]

            location = None
            if device_data.get("location") and device_data["location"].get("name"):
                location = device_data["location"]["name"]

            platform = None
            platform_network_driver = None
            if device_data.get("platform"):
                platform = device_data["platform"].get("name")
                platform_network_driver = device_data["platform"].get("network_driver")

            tags = []
            if device_data.get("tags"):
                tags = [tag.get("name", "") for tag in device_data["tags"] if tag.get("name")]

            device = DeviceInfo(
                id=device_data.get("id", ""),
                name=device_data.get("name"),
                serial=device_data.get("serial"),
                primary_ip4=primary_ip,
                status=status,
                device_type=device_type,
                role=role,
                location=location,
                platform=platform,
                platform_network_driver=platform_network_driver,
                tags=tags,
                manufacturer=manufacturer,
            )

            devices.append(device)

        return devices
