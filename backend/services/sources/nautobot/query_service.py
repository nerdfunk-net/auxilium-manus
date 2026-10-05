"""
Inventory query service — Nautobot GraphQL query methods for device lookups.

Extracted from InventoryService as part of Phase 4 decomposition.
See: doc/refactoring/REFACTORING_SERVICES.md — Phase 4

Cache layout (per Nautobot instance, scope = ``credentials.cache_scope``), all
Redis HASHes refreshed atomically by the "RefreshNautobotDeviceCache" Hatchet cron
workflow (see hatchet/workflows/cache_devices.py):
    nautobot:devices:data:<scope>            device_id -> JSON of one device
    nautobot:devices:idx:<scope>:<field>     field value -> JSON list of device ids
                                             (field in ``INDEXED_FIELDS``)
  Equality filters on an indexed field (role, status, device_type, manufacturer,
  platform) read the id list from the index and fetch only those devices (HMGET), so
  they never deserialise the whole fleet. Every other filter (name, tag, custom
  field, has_primary, ...) loads the full list (HVALS) and filters in Python. The full
  list is held in self._devices_cache for the lifetime of the service instance so
  multiple conditions in the same inventory preview only pay the Redis round-trip once.
  If the cache is cold/unavailable everything falls back to a live Nautobot query.

  Exceptions that still go directly to Nautobot GraphQL:
    • location       — exact match only (equals / not equals, never "contains");
                        Nautobot resolves child-location hierarchy server-side;
                        each distinct filter's result is cached in Redis for
                        ``location_ttl`` (default 10 min, key
                        nautobot:devices:location:<scope>:<mode>:<filter>),
                        empty/errored results are never cached, and the 5-minute
                        bulk refresh drops them all (per Nautobot instance) as soon
                        as it sees any device added, removed, moved or edited — so
                        changes normally show up on the next cron cycle rather than
                        after the TTL
    • ip_prefix      — requires server-side CIDR containment logic
    • primary_prefix — requires server-side CIDR containment logic, restricted
                        to each device's primary_ip4

  Custom field values (Nautobot's ``_custom_field_data``) are fetched and
  cached alongside the other device attributes, so custom-field filters are
  cache-first too — see ``_query_devices_by_custom_field`` below.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from models.sources_nautobot import DeviceInfo
from services.sources.nautobot.live_query_mixin import NautobotLiveQueryMixin

if TYPE_CHECKING:
    from services.cache.redis_cache_service import RedisCacheService
    from services.nautobot.client import NautobotService
    from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)

_BULK_CACHE_KEY_PREFIX = "nautobot:devices:data"
_INDEX_CACHE_KEY_PREFIX = "nautobot:devices:idx"
# Single-valued DeviceInfo attributes that get a value -> device ids index.
INDEXED_FIELDS = ("role", "status", "device_type", "manufacturer", "platform")


def _bulk_payload_changed(
    previous: list[dict[str, Any]] | None, current: list[dict[str, Any]]
) -> bool:
    """True when the device data differs from the previous bulk entry.

    An absent/unreadable previous entry counts as changed: we can't tell what
    moved, so the safe answer is to invalidate. Order is irrelevant.
    """
    if not isinstance(previous, list) or any(
        not isinstance(d, dict) or "id" not in d for d in previous
    ):
        return True
    return {d["id"]: d for d in previous} != {d["id"]: d for d in current}


def _custom_field_value_matches(stored: Any, target: str, use_contains: bool) -> bool:
    """Compare a cached custom field value (scalar or multi-select list) to ``target``."""
    if stored is None:
        return False
    values = stored if isinstance(stored, list) else [stored]
    if use_contains:
        needle = target.lower()
        return any(needle in str(value).lower() for value in values)
    return any(str(value) == target for value in values)


# (field, value, negate): a device matches when ``(getattr(device, field) == value) != negate``.
_Predicate = tuple[str, str, bool]


def _matches_all(device: DeviceInfo, predicates: Sequence[_Predicate]) -> bool:
    return all((getattr(device, field) == value) != negate for field, value, negate in predicates)


class NautobotSourceQueryService(NautobotLiveQueryMixin):
    """Handles all Nautobot GraphQL queries for inventory device lookups."""

    def __init__(
        self,
        nautobot: NautobotService,
        credentials: NautobotCredentials,
        cache_service: RedisCacheService | None = None,
        bulk_ttl: int = 1800,
        location_ttl: int = 600,
    ):

        self._nautobot = nautobot
        self._credentials = credentials
        self._cache_service = cache_service
        self._bulk_cache_key = f"{_BULK_CACHE_KEY_PREFIX}:{credentials.cache_scope}"
        self._bulk_ttl = bulk_ttl
        # TTL for the per-filter location cache (live_query_mixin).
        self._location_ttl = location_ttl
        self._devices_cache: list[DeviceInfo] | None = None

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
            custom_fields=raw.get("custom_fields") or {},
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
                started = time.perf_counter()
                raw_list = self._cache_service.hvals_json(self._bulk_cache_key)
                fetched = time.perf_counter()
                if raw_list:
                    devices = [self._parse_device_from_cache(d) for d in raw_list]
                    logger.info(
                        "Cache hit for '%s': %s devices (redis %.1f ms, parse %.1f ms)",
                        self._bulk_cache_key,
                        len(devices),
                        (fetched - started) * 1000,
                        (time.perf_counter() - fetched) * 1000,
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

    async def refresh_bulk_cache(self, *, force_invalidate: bool = False) -> int:
        """Fetch all devices live and (re)populate the Redis bulk cache.

        Called by the "RefreshNautobotDeviceCache" Hatchet cron workflow. Returns
        the number of devices written, or 0 if caching is disabled (no cache
        service configured).

        Cached location filters are dropped when the device data changed since
        the previous snapshot, or unconditionally with ``force_invalidate``
        (the "Rebuild cache" button), which then also re-runs the location filters
        that were cached, so the ones people actually use are warm again.
        """
        if self._cache_service is None:
            return 0

        # Note the cached location filters before they are dropped (rebuild only).
        warm_filters = self._cached_location_filters() if force_invalidate else []
        devices = await self._query_all_devices_live()
        payload = [d.model_dump() for d in devices]
        previous = self._read_bulk_payload()
        if not self._cache_service.replace_hashes(
            {
                self._bulk_cache_key: {d["id"]: d for d in payload},
                **{
                    self._index_key(field): self._build_index(devices, field)
                    for field in INDEXED_FIELDS
                },
            },
            self._bulk_ttl,
        ):
            logger.warning("Could not write the bulk device cache '%s'", self._bulk_cache_key)
        self._devices_cache = devices
        logger.info(
            "Refreshed bulk cache '%s' with %s devices (ttl=%ss)",
            self._bulk_cache_key,
            len(payload),
            self._bulk_ttl,
        )
        # Cached location filters hold full device data too, so any change here
        # (device added/removed/moved, or a detail such as its primary IP edited)
        # must not keep being served from them until their own TTL runs out.
        if force_invalidate or _bulk_payload_changed(previous, payload):
            removed = self._invalidate_location_cache()
            logger.info("Bulk device data changed; dropped %s cached location filter(s)", removed)
        if warm_filters:
            warmed = await self._rewarm_location_filters(warm_filters)
            logger.info("Re-warmed %s/%s location filter(s)", warmed, len(warm_filters))
        return len(payload)

    def _read_bulk_payload(self) -> list[dict[str, Any]] | None:
        """The bulk entry currently in Redis, or None if absent/unreadable."""
        if self._cache_service is None:
            return None
        try:
            return self._cache_service.hvals_json(self._bulk_cache_key)
        except Exception as exc:
            logger.warning("Redis read failed for '%s': %s", self._bulk_cache_key, exc)
            return None

    # ------------------------------------------------------------------
    # Attribute indexes (value -> device ids)
    # ------------------------------------------------------------------

    def _index_key(self, field: str) -> str:
        return f"{_INDEX_CACHE_KEY_PREFIX}:{self._credentials.cache_scope}:{field}"

    @staticmethod
    def _build_index(devices: list[DeviceInfo], field: str) -> dict[str, list[str]]:
        """``{value: [device ids]}`` for one attribute; devices without a value are
        left out (a negated filter gets them as "all ids minus the matching ones")."""
        index: dict[str, list[str]] = {}
        for device in devices:
            value = getattr(device, field)
            if value:
                index.setdefault(value, []).append(device.id)
        return index

    def _read_index_ids(self, field: str, value: str, negate: bool) -> set[str] | None:
        """Ids of the devices whose ``field`` equals (or, ``negate``, differs from)
        ``value`` — read from the index without touching any device. None when the
        cache cannot answer (cold, index missing, Redis error)."""
        cache = self._cache_service
        if cache is None:
            return None
        try:
            index_key = self._index_key(field)
            ids = cache.hget_json(index_key, value)
            if ids is None:
                if not cache.hash_exists(index_key):
                    return None  # cold cache, or nobody has any value for this field
                ids = []  # warm cache, no device has this value
            if not isinstance(ids, list):
                return None
            if not negate:
                return set(ids)
            all_ids = cache.hkeys(self._bulk_cache_key)
            return set(all_ids) - set(ids) if all_ids else None
        except Exception as exc:
            logger.warning("Redis index read failed for '%s': %s", self._index_key(field), exc)
            return None

    def _fetch_devices(
        self, ids: set[str], predicates: Sequence[_Predicate] = ()
    ) -> list[DeviceInfo] | None:
        """Only the devices with these ids from the data hash (HMGET), each checked against
        the ``predicates`` that selected it. The id list and the bodies come from separate
        Redis commands, so a cron swap in between can leave them from different snapshots:
        an id that vanished, or a body that no longer matches, discards the whole read.
        None then (or when Redis cannot answer) so the caller falls back to the full list,
        which is a single snapshot."""
        cache = self._cache_service
        if cache is None:
            return None
        if not ids:
            return []
        try:
            started = time.perf_counter()
            raws = cache.hmget_json(self._bulk_cache_key, list(ids))
            if raws is None or not all(isinstance(r, dict) for r in raws):
                logger.info("Cache index and data disagree, falling back to the full list")
                return None
            fetched = time.perf_counter()
            devices = [self._parse_device_from_cache(r) for r in raws if isinstance(r, dict)]
        except Exception as exc:
            logger.warning("Redis read failed for '%s': %s", self._bulk_cache_key, exc)
            return None
        if not all(_matches_all(d, predicates) for d in devices):
            logger.info("Cache index is stale for the fetched devices, falling back")
            return None
        logger.info(
            "Cache fetch of %s devices by id (redis %.1f ms, parse %.1f ms)",
            len(devices),
            (fetched - started) * 1000,
            (time.perf_counter() - fetched) * 1000,
        )
        return devices

    async def _ids_by_attribute(self, field: str, value: str, negate: bool = False) -> set[str]:
        """Ids of the devices matching an indexed attribute, cheapest source first: the
        in-memory list, then the Redis index (no device is parsed), then the full list."""
        if self._devices_cache is None:
            ids = self._read_index_ids(field, value, negate)
            if ids is not None:
                return ids
        all_devices = await self._get_all_devices_cached()
        return {d.id for d in all_devices if (getattr(d, field) == value) != negate}

    async def _devices_by_ids(
        self, ids: set[str], predicates: Sequence[_Predicate] = ()
    ) -> list[DeviceInfo]:
        """The devices with these ids, fetching only those from Redis when possible.
        ``predicates`` are what selected the ids; they verify the fetched bodies and, on a
        fallback, are re-evaluated on the full list instead of trusting the id list."""
        if self._devices_cache is None:
            fetched = self._fetch_devices(ids, predicates)
            if fetched is not None:
                return fetched
        all_devices = await self._get_all_devices_cached()
        if predicates:
            return [d for d in all_devices if _matches_all(d, predicates)]
        return [d for d in all_devices if d.id in ids]

    @contextmanager
    def narrowed_to(self, devices: list[DeviceInfo]) -> Iterator[None]:
        """Within the block the "full" device list is ``devices``, so scan-style filters
        (name, tag, custom field, ...) only look at devices an AND has already narrowed
        down. The previous list is restored on exit, also on errors."""
        previous = self._devices_cache
        self._devices_cache = devices
        try:
            yield
        finally:
            self._devices_cache = previous

    async def _devices_by_attribute(
        self, field: str, value: str, *, negate: bool = False
    ) -> list[DeviceInfo]:
        """Equality (or inequality) filter on an indexed attribute. Equality reads only the
        matching devices; inequality matches most of the fleet, so it filters the full list."""
        if not negate and self._devices_cache is None:
            ids = self._read_index_ids(field, value, negate=False)
            if ids is not None:
                fetched = self._fetch_devices(ids, [(field, value, False)])
                if fetched is not None:
                    return fetched
        all_devices = await self._get_all_devices_cached()
        return [d for d in all_devices if (getattr(d, field) == value) != negate]

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
                _custom_field_data
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

        result = await self._devices_by_attribute("role", role_filter, negate=use_negation)

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

        result = await self._devices_by_attribute("status", status_filter)
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

        result = await self._devices_by_attribute(
            "device_type", devicetype_filter, negate=use_negation
        )

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

        result = await self._devices_by_attribute(
            "manufacturer", manufacturer_filter, negate=use_negation
        )

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

        result = await self._devices_by_attribute("platform", platform_filter)
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

    async def _query_devices_by_custom_field(
        self,
        custom_field_name: str,
        custom_field_value: str,
        use_contains: bool = False,
    ) -> list[DeviceInfo]:
        """Filter devices by custom field value using the bulk cache.

        Args:
            custom_field_name: Name of the custom field (with cf_ prefix)
            custom_field_value: Value to search for
            use_contains: Whether to use contains (case-insensitive) or exact match
        """
        if (
            not custom_field_name
            or not custom_field_value
            or (isinstance(custom_field_value, str) and custom_field_value.strip() == "")
        ):
            logger.warning(
                "Empty custom_field_name or custom_field_value provided, returning empty result"
            )
            return []

        cf_key = custom_field_name.removeprefix("cf_")
        all_devices = await self._get_all_devices_cached()
        result = [
            d
            for d in all_devices
            if _custom_field_value_matches(
                d.custom_fields.get(cf_key), custom_field_value, use_contains
            )
        ]
        logger.info(
            "Cache filter custom_field='%s' (contains=%s): %s devices",
            cf_key,
            use_contains,
            len(result),
        )
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
                custom_fields=device_data.get("_custom_field_data") or {},
            )

            devices.append(device)

        return devices
