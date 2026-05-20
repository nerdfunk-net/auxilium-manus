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
    • location  — Nautobot resolves child-location hierarchy server-side
    • ip_prefix — requires server-side CIDR containment logic
    • custom_field — fields are dynamic and not stored in the cache
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from models.sources_nautobot import DeviceInfo

if TYPE_CHECKING:
    from services.cache.redis_cache_service import RedisCacheService

logger = logging.getLogger(__name__)

_BULK_CACHE_KEY_PREFIX = "nautobot:devices:all"


class NautobotSourceQueryService:
    """Handles all Nautobot GraphQL queries for inventory device lookups."""

    def __init__(
        self,
        nautobot: "NautobotService",
        credentials: "NautobotCredentials",
        cache_service: Optional["RedisCacheService"] = None,
    ):
        from services.nautobot.client import NautobotService
        from services.nautobot.credentials import NautobotCredentials

        self._nautobot = nautobot
        self._credentials = credentials
        self._cache_service = cache_service
        self._bulk_cache_key = f"{_BULK_CACHE_KEY_PREFIX}:{credentials.cache_scope}"
        self._devices_cache: Optional[List[DeviceInfo]] = None
        self._custom_field_types_cache: Optional[Dict[str, str]] = None

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _parse_device_from_cache(self, raw: Dict[str, Any]) -> DeviceInfo:
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
            tags=tags,
            manufacturer=raw.get("manufacturer"),
        )

    async def _get_all_devices_cached(self) -> List[DeviceInfo]:
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

    async def _get_custom_field_types(self) -> Dict[str, str]:
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
                    field_type_dict.get("value")
                    if isinstance(field_type_dict, dict)
                    else None
                )

                if field_key and field_type_value:
                    type_mapping[field_key] = field_type_value
                    logger.info(
                        "Custom field '%s' has type '%s'", field_key, field_type_value
                    )

            logger.info(
                "Loaded %s custom field types: %s", len(type_mapping), type_mapping
            )

            self._custom_field_types_cache = type_mapping
            return type_mapping

        except Exception as e:
            logger.error("Error fetching custom field types: %s", e, exc_info=True)
            return {}

    # ------------------------------------------------------------------
    # Live Nautobot GraphQL helpers (used as fallback or for uncacheable queries)
    # ------------------------------------------------------------------

    async def _query_all_devices_live(self) -> List[DeviceInfo]:
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
                }
            }
        }
        """

        result = await self._nautobot.graphql_query(query, {}, self._credentials)
        devices_data = result.get("data", {}).get("devices", [])
        logger.info("Retrieved %s total devices from Nautobot", len(devices_data))
        return self._parse_device_data(devices_data)

    async def _query_all_devices(self) -> List[DeviceInfo]:
        """Return all devices, using the bulk cache when available."""
        return await self._get_all_devices_cached()

    # ------------------------------------------------------------------
    # Cache-first query methods
    # ------------------------------------------------------------------

    async def _query_devices_by_name(
        self, name_filter: str, use_contains: bool = False
    ) -> List[DeviceInfo]:
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
    ) -> List[DeviceInfo]:
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

    async def _query_devices_by_status(self, status_filter: str) -> List[DeviceInfo]:
        """Filter devices by status using the bulk cache."""
        if not status_filter or status_filter.strip() == "":
            logger.warning("Empty status_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()
        result = [d for d in all_devices if d.status == status_filter]
        logger.info("Cache filter status='%s': %s devices", status_filter, len(result))
        return result

    async def _query_devices_by_tag(self, tag_filter: str) -> List[DeviceInfo]:
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
    ) -> List[DeviceInfo]:
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
    ) -> List[DeviceInfo]:
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

    async def _query_devices_by_platform(
        self, platform_filter: str
    ) -> List[DeviceInfo]:
        """Filter devices by platform using the bulk cache."""
        if not platform_filter or platform_filter.strip() == "":
            logger.warning("Empty platform_filter provided, returning empty result")
            return []

        all_devices = await self._get_all_devices_cached()
        result = [d for d in all_devices if d.platform == platform_filter]
        logger.info(
            "Cache filter platform='%s': %s devices", platform_filter, len(result)
        )
        return result

    async def _query_devices_by_has_primary(
        self, has_primary_filter: str
    ) -> List[DeviceInfo]:
        """Filter devices by whether they have a primary IP using the bulk cache."""
        has_primary_bool = has_primary_filter.lower() == "true"

        all_devices = await self._get_all_devices_cached()

        if has_primary_bool:
            result = [d for d in all_devices if d.primary_ip4]
        else:
            result = [d for d in all_devices if not d.primary_ip4]

        logger.info(
            "Cache filter has_primary=%s: %s devices", has_primary_bool, len(result)
        )
        return result

    # ------------------------------------------------------------------
    # Live Nautobot queries (location hierarchy / CIDR / custom fields)
    # ------------------------------------------------------------------

    async def _query_devices_by_location(
        self,
        location_filter: str,
        use_contains: bool = False,
        use_negation: bool = False,
    ) -> List[DeviceInfo]:
        """Query devices by location using GraphQL.

        Intentionally kept as a live Nautobot call: Nautobot resolves the full
        child-location hierarchy server-side.  Replicating that logic in Python
        would require fetching and traversing the entire location tree, which is
        more expensive than a single filtered GraphQL query.

        Args:
            location_filter: Location name or ID to filter by
            use_contains: Use case-insensitive contains matching
            use_negation: Use negation (location__n) to exclude devices from this location
        """
        if not location_filter or location_filter.strip() == "":
            logger.warning("Empty location_filter provided, returning empty result")
            return []

        if use_negation:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location__n: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
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
                    tags {
                        name
                    }
                    platform {
                        name
                    }
                }
            }
            """
        elif use_contains:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location__name__ic: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
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
                    tags {
                        name
                    }
                    platform {
                        name
                    }
                }
            }
            """
        else:
            query = """
            query devices_by_location ($location_filter: [String]) {
                devices (location: $location_filter) {
                    id
                    name
                    serial
                    role {
                        name
                    }
                    location {
                        name
                    }
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
                    tags {
                        name
                    }
                    platform {
                        name
                    }
                }
            }
            """

        variables = {"location_filter": [location_filter]}
        result = await self._nautobot.graphql_query(query, variables, self._credentials)

        logger.info(
            "GraphQL result for location query '%s': Found %s devices",
            location_filter,
            len(result.get("data", {}).get("devices", [])),
        )

        devices_data = result.get("data", {}).get("devices", [])
        return self._parse_device_data(devices_data)

    async def _query_devices_by_ip_prefix(
        self, prefix_filter: str, operator: str = "within_include"
    ) -> List[DeviceInfo]:
        """Query devices by IP prefix using GraphQL.

        Intentionally kept as a live Nautobot call: CIDR containment filtering
        (within_include / within / exact) requires server-side evaluation.

        Traverses: prefixes → ip_addresses → interface_assignments → interface → device.
        IP addresses without interface assignments are ignored.
        Devices are deduplicated by ID.

        The value may optionally include a namespace name after the CIDR, separated by
        a space (e.g. "192.168.183.0/24 Global"). When present, the namespace is added
        as an additional filter to the GraphQL query.

        Args:
            prefix_filter: CIDR notation with optional namespace
                           (e.g., "192.168.183.0/24" or "192.168.183.0/24 Global")
            operator: One of "within_include", "within", "exact"
        """
        if not prefix_filter or prefix_filter.strip() == "":
            logger.warning("Empty prefix_filter provided, returning empty result")
            return []

        # Split CIDR and optional namespace: "192.168.183.0/24 Global" → ("192.168.183.0/24", "Global")
        parts = prefix_filter.strip().split(None, 1)
        cidr = parts[0]
        namespace = parts[1].strip() if len(parts) > 1 else None

        namespace_arg = f', namespace: "{namespace}"' if namespace else ""

        if operator == "within":
            prefix_arg = f'within: "{cidr}"{namespace_arg}'
        elif operator == "exact":
            prefix_arg = f'prefix: "{cidr}"{namespace_arg}'
        else:
            prefix_arg = f'within_include: "{cidr}"{namespace_arg}'

        logger.info(
            "ip_prefix query: cidr='%s', namespace=%s, operator=%s",
            cidr,
            namespace,
            operator,
        )

        query = f"""
        query devices_by_ip_prefix {{
            prefixes({prefix_arg}) {{
                ip_addresses {{
                    interface_assignments {{
                        interface {{
                            device {{
                                id
                                name
                                serial
                                primary_ip4 {{ address }}
                                status {{ name }}
                                device_type {{ model manufacturer {{ name }} }}
                                role {{ name }}
                                location {{ name }}
                                tags {{ name }}
                                platform {{ name }}
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """

        result = await self._nautobot.graphql_query(query, {}, self._credentials)

        if "errors" in result:
            logger.error("GraphQL errors in ip_prefix query: %s", result["errors"])
            return []

        prefixes_data = result.get("data", {}).get("prefixes", [])
        seen_ids: Dict[str, DeviceInfo] = {}

        for prefix in prefixes_data:
            for ip_addr in prefix.get("ip_addresses", []):
                for assignment in ip_addr.get("interface_assignments", []):
                    interface = assignment.get("interface") or {}
                    device_data = interface.get("device") or {}
                    device_id = device_data.get("id")
                    if device_id and device_id not in seen_ids:
                        parsed = self._parse_device_data([device_data])
                        if parsed:
                            seen_ids[device_id] = parsed[0]

        devices = list(seen_ids.values())
        logger.info(
            "ip_prefix query '%s' namespace=%s (operator=%s) returned %s unique devices",
            cidr,
            namespace,
            operator,
            len(devices),
        )
        return devices

    async def _query_devices_by_custom_field(
        self,
        custom_field_name: str,
        custom_field_value: str,
        use_contains: bool = False,
    ) -> List[DeviceInfo]:
        """
        Query devices by custom field value.

        Intentionally kept as a live Nautobot call: custom fields are dynamic
        and not stored in the bulk device cache.

        Args:
            custom_field_name: Name of the custom field (with cf_ prefix)
            custom_field_value: Value to search for
            use_contains: Whether to use contains (icontains) or exact match

        Returns:
            List of matching devices
        """
        try:

            if (
                not custom_field_name
                or not custom_field_value
                or (
                    isinstance(custom_field_value, str)
                    and custom_field_value.strip() == ""
                )
            ):
                logger.warning(
                    "Empty custom_field_name or custom_field_value provided, returning empty result"
                )
                return []

            custom_field_types = await self._get_custom_field_types()

            cf_key = custom_field_name.replace("cf_", "")
            cf_type = custom_field_types.get(cf_key)

            if cf_type == "select":
                graphql_var_type = "[String]"
            elif use_contains:
                graphql_var_type = "[String]"
            else:
                graphql_var_type = "String"

            logger.info(
                "Custom field '%s' type='%s', use_contains=%s, GraphQL type='%s'",
                cf_key,
                cf_type,
                use_contains,
                graphql_var_type,
            )

            filter_field = custom_field_name

            if use_contains:
                query = f"""
                query devices_by_custom_field($field_value: {graphql_var_type}) {{
                  devices({filter_field}__ic: $field_value) {{
                    id
                    name
                    serial
                    role {{
                      name
                    }}
                    location {{
                      name
                    }}
                    primary_ip4 {{
                      address
                    }}
                    status {{
                      name
                    }}
                    device_type {{
                      model
                      manufacturer {{
                        name
                      }}
                    }}
                    tags {{
                      name
                    }}
                    platform {{
                      name
                    }}
                  }}
                }}
                """
            else:
                query = f"""
                query devices_by_custom_field($field_value: {graphql_var_type}) {{
                  devices({filter_field}: $field_value) {{
                    id
                    name
                    serial
                    role {{
                      name
                    }}
                    location {{
                      name
                    }}
                    primary_ip4 {{
                      address
                    }}
                    status {{
                      name
                    }}
                    device_type {{
                      model
                      manufacturer {{
                        name
                      }}
                    }}
                    tags {{
                      name
                    }}
                    platform {{
                      name
                    }}
                  }}
                }}
                """

            if graphql_var_type == "[String]":
                variables = {"field_value": [custom_field_value]}
            else:
                variables = {"field_value": custom_field_value}

            logger.debug("Custom field '%s' GraphQL query:\n%s", cf_key, query)
            logger.debug("Custom field '%s' variables: %s", cf_key, variables)
            logger.info(
                "Custom field '%s' filter: %s, type: %s, graphql_var_type: %s",
                cf_key,
                filter_field,
                cf_type,
                graphql_var_type,
            )

            result = await self._nautobot.graphql_query(query, variables, self._credentials)

            if "errors" in result:
                logger.error(
                    "GraphQL errors in custom field query: %s", result["errors"]
                )
                return []

            return self._parse_device_data(result.get("data", {}).get("devices", []))

        except Exception as e:
            logger.error(
                "Error querying devices by custom field '%s': %s", custom_field_name, e
            )
            return []

    # ------------------------------------------------------------------
    # Shared parser
    # ------------------------------------------------------------------

    def _parse_device_data(
        self, devices_data: List[Dict[str, Any]]
    ) -> List[DeviceInfo]:
        """Parse GraphQL device data (nested dicts) into DeviceInfo objects."""
        devices = []

        for device_data in devices_data:
            primary_ip = None
            if device_data.get("primary_ip4") and device_data["primary_ip4"].get(
                "address"
            ):
                primary_ip = device_data["primary_ip4"]["address"]

            status = None
            if device_data.get("status") and device_data["status"].get("name"):
                status = device_data["status"]["name"]

            device_type = None
            if device_data.get("device_type") and device_data["device_type"].get(
                "model"
            ):
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
            if device_data.get("platform") and device_data["platform"].get("name"):
                platform = device_data["platform"]["name"]

            tags = []
            if device_data.get("tags"):
                tags = [
                    tag.get("name", "")
                    for tag in device_data["tags"]
                    if tag.get("name")
                ]

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
                tags=tags,
                manufacturer=manufacturer,
            )

            devices.append(device)

        return devices
