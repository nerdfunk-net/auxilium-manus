"""Live Nautobot GraphQL queries for location / CIDR / custom-field filters.

Extracted from query_service.py to keep the cache-first query service under
the project file-size limit. Mixed into NautobotSourceQueryService.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, unquote

from models.sources_nautobot import DeviceInfo

if TYPE_CHECKING:
    from services.cache.redis_cache_service import RedisCacheService
    from services.nautobot.client import NautobotService
    from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)

_DEVICE_SELECTION_FIELDS = """
                    id
                    name
                    serial
                    _custom_field_data
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
                        network_driver
                    }
"""


_LOCATION_CACHE_KEY_PREFIX = "nautobot:devices:location"
# Nautobot queries in flight at once while re-warming location filters.
_REWARM_CONCURRENCY = 5


# Locations are matched exactly: "equals" or "not equals" only. Nautobot's GraphQL
# `devices()` accepts just `location` and `location__n` (there is no name-contains
# argument), and "Location contains City" must never match "City A".
# Inverse of ``_location_match_mode``: key segment -> use_negation.
_LOCATION_MATCH_MODES: dict[str, bool] = {"eq": False, "not": True}


def _location_match_mode(use_negation: bool) -> str:
    return "not" if use_negation else "eq"


def _resolve_location_filter_arg(use_negation: bool) -> str:
    return "location__n: $location_filter" if use_negation else "location: $location_filter"


def _location_devices_query(filter_arg: str) -> str:
    return f"""
            query devices_by_location ($location_filter: [String]) {{
                devices ({filter_arg}) {{
                    {_DEVICE_SELECTION_FIELDS}
                }}
            }}
            """


class NautobotLiveQueryMixin:
    """Mixin providing live GraphQL query helpers used by NautobotSourceQueryService."""

    # Provided by NautobotSourceQueryService (declared here for type checking only).
    _nautobot: NautobotService
    _credentials: NautobotCredentials
    _cache_service: RedisCacheService | None
    _location_ttl: int

    if TYPE_CHECKING:

        def _parse_device_data(self, devices_data: list[dict[str, Any]]) -> list[DeviceInfo]: ...

        def _parse_device_from_cache(self, raw: dict[str, Any]) -> DeviceInfo: ...

    async def _query_devices_by_location(
        self,
        location_filter: str,
        use_negation: bool = False,
    ) -> list[DeviceInfo]:
        """Query devices by location using GraphQL (exact match only).

        Intentionally a Nautobot GraphQL call rather than a filter over the bulk
        device cache: Nautobot resolves the full child-location hierarchy
        server-side, and the cached devices only carry their own location name.
        The result of each distinct filter is cached in Redis for a short TTL
        (``location_ttl``, default 10 min) — see ``_location_cache_key`` — and
        is dropped early by ``refresh_bulk_cache`` when device data changed.

        Args:
            location_filter: Location name or ID to filter by (exact match; there is
                deliberately no "contains" mode for locations)
            use_negation: Use negation (location__n) to exclude devices from this location
        """
        if not location_filter or location_filter.strip() == "":
            logger.warning("Empty location_filter provided, returning empty result")
            return []

        location_filter = location_filter.strip()
        cache_key = self._location_cache_key(location_filter, use_negation)
        cached = self._read_location_cache(cache_key)
        if cached is not None:
            return cached

        filter_arg = _resolve_location_filter_arg(use_negation)
        query = _location_devices_query(filter_arg)
        variables = {"location_filter": [location_filter]}
        result = await self._nautobot.graphql_query(query, variables, self._credentials)

        devices_data = (result.get("data") or {}).get("devices") or []
        logger.info(
            "GraphQL result for location query '%s': Found %s devices",
            location_filter,
            len(devices_data),
        )

        devices = self._parse_device_data(devices_data)
        # Only successful, non-empty results are cached: an empty result may be a
        # location that was just created or populated and must show up on the
        # next run, and a partial/errored response must never be served again.
        if devices and not result.get("errors"):
            self._write_location_cache(cache_key, devices)
        return devices

    def _location_cache_key(self, location_filter: str, use_negation: bool) -> str:
        """`nautobot:devices:location:<scope>:<eq|not>:<filter>`, scoped per Nautobot
        instance/token; the filter is percent-encoded so awkward location names
        (spaces, colons, wildcards) can't break the key or its namespace."""
        mode = _location_match_mode(use_negation)
        return f"{self._location_cache_namespace()}:{mode}:{quote(location_filter, safe='')}"

    def _location_cache_namespace(self) -> str:
        """Prefix shared by every location-filter entry of this Nautobot instance."""
        return f"{_LOCATION_CACHE_KEY_PREFIX}:{self._credentials.cache_scope}"

    def _cached_location_filters(self) -> list[tuple[str, bool]]:
        """The ``(location, use_negation)`` filters currently cached for this
        Nautobot instance, recovered from their keys (best-effort). Entries with an
        unknown mode (e.g. left over from an older key format) are ignored."""
        if self._cache_service is None:
            return []
        namespace = self._location_cache_namespace()
        try:
            keys = self._cache_service.list_keys(namespace)
        except Exception as exc:
            logger.warning("Could not list cached location filters: %s", exc)
            return []
        filters: list[tuple[str, bool]] = []
        for key in keys:
            mode, _, quoted = key[len(namespace) + 1 :].partition(":")
            if mode in _LOCATION_MATCH_MODES and quoted:
                filters.append((unquote(quoted), _LOCATION_MATCH_MODES[mode]))
        return filters

    async def _rewarm_location_filters(self, filters: list[tuple[str, bool]]) -> int:
        """Re-run ``filters`` against Nautobot so they are cached again.

        Bounded parallelism; one failing filter never affects the others (it just
        stays uncached until its next use). Returns how many were re-run cleanly.
        """
        semaphore = asyncio.Semaphore(_REWARM_CONCURRENCY)

        async def _one(location: str, negation: bool) -> bool:
            async with semaphore:
                try:
                    await self._query_devices_by_location(location, negation)
                    return True
                except Exception as exc:
                    logger.warning("Could not re-warm location filter '%s': %s", location, exc)
                    return False

        results = await asyncio.gather(*(_one(*f) for f in filters))
        return sum(results)

    def _invalidate_location_cache(self) -> int:
        """Drop every cached location filter of this Nautobot instance.

        Best-effort (never raises): the entries just expire on their TTL if
        Redis is unavailable. Returns the number of entries removed.
        """
        if self._cache_service is None:
            return 0
        try:
            return self._cache_service.clear_namespace(self._location_cache_namespace())
        except Exception as exc:
            logger.warning("Could not invalidate the location cache: %s", exc)
            return 0

    def _read_location_cache(self, cache_key: str) -> list[DeviceInfo] | None:
        if self._cache_service is None:
            return None
        try:
            raw_list: list[dict[str, Any]] | None = self._cache_service.get(cache_key)
            if not raw_list:
                return None
            devices = [self._parse_device_from_cache(raw) for raw in raw_list]
            logger.info("Cache hit for '%s': %s devices", cache_key, len(devices))
            return devices
        except Exception as exc:
            logger.warning("Redis read failed for '%s', querying Nautobot: %s", cache_key, exc)
            return None

    def _write_location_cache(self, cache_key: str, devices: list[DeviceInfo]) -> None:
        if self._cache_service is None:
            return
        try:
            self._cache_service.set(
                cache_key, [d.model_dump() for d in devices], self._location_ttl
            )
        except Exception as exc:
            logger.warning("Redis write failed for '%s': %s", cache_key, exc)

    async def _query_devices_by_ip_prefix(
        self, prefix_filter: str, operator: str = "within_include"
    ) -> list[DeviceInfo]:
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

        # Split optional namespace: "192.168.183.0/24 Global" -> cidr + namespace
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
                                _custom_field_data
                                primary_ip4 {{ address }}
                                status {{ name }}
                                device_type {{ model manufacturer {{ name }} }}
                                role {{ name }}
                                location {{ name }}
                                tags {{ name }}
                                platform {{ name network_driver }}
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
        seen_ids: dict[str, DeviceInfo] = {}

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

    async def _query_devices_by_primary_prefix(
        self, prefix_filter: str, operator: str = "within_include"
    ) -> list[DeviceInfo]:
        """Query devices whose *primary* IPv4 address falls within a prefix.

        Intentionally kept as a live Nautobot call: CIDR containment filtering
        requires server-side evaluation.

        Unlike ip_prefix (which matches devices with ANY interface address in
        the prefix), this only matches devices where the in-prefix address is
        their primary_ip4 — done by querying ip_addresses(...) and only
        counting devices that appear under each address's primary_ip4_for.

        Note: unlike prefixes(...), Nautobot's ip_addresses(...) GraphQL field
        does not accept within_include/within arguments — only prefix (which
        already behaves like within_include, matching all addresses contained
        in the CIDR including network/broadcast). The operator parameter is
        kept for interface parity with _query_devices_by_ip_prefix and future
        extensibility, but only "within_include" is currently supported.
        """
        if not prefix_filter or prefix_filter.strip() == "":
            logger.warning("Empty prefix_filter provided, returning empty result")
            return []

        parts = prefix_filter.strip().split(None, 1)
        cidr = parts[0]
        namespace = parts[1].strip() if len(parts) > 1 else None

        namespace_arg = f', namespace: "{namespace}"' if namespace else ""
        prefix_arg = f'prefix: "{cidr}"{namespace_arg}'

        logger.info(
            "primary_prefix query: cidr='%s', namespace=%s, operator=%s",
            cidr,
            namespace,
            operator,
        )

        query = f"""
        query devices_by_primary_prefix {{
            ip_addresses({prefix_arg}) {{
                address
                primary_ip4_for {{
                    id
                    name
                    serial
                    _custom_field_data
                    primary_ip4 {{ address }}
                    status {{ name }}
                    device_type {{ model manufacturer {{ name }} }}
                    role {{ name }}
                    location {{ name }}
                    tags {{ name }}
                    platform {{ name network_driver }}
                }}
            }}
        }}
        """

        result = await self._nautobot.graphql_query(query, {}, self._credentials)

        if "errors" in result:
            logger.error("GraphQL errors in primary_prefix query: %s", result["errors"])
            return []

        ip_addresses_data = result.get("data", {}).get("ip_addresses", [])
        seen_ids: dict[str, DeviceInfo] = {}

        for ip_addr in ip_addresses_data:
            for device_data in ip_addr.get("primary_ip4_for", []):
                device_id = device_data.get("id")
                if device_id and device_id not in seen_ids:
                    parsed = self._parse_device_data([device_data])
                    if parsed:
                        seen_ids[device_id] = parsed[0]

        devices = list(seen_ids.values())
        logger.info(
            "primary_prefix query '%s' namespace=%s (operator=%s) returned %s unique devices",
            cidr,
            namespace,
            operator,
            len(devices),
        )
        return devices
