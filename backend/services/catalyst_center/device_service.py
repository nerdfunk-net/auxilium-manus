"""Version-agnostic device inventory access for Cisco Catalyst Center."""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from typing import Any

from models.catalyst_center import CatalystCenterDevice
from services.catalyst_center.client import RELEASE_PATH, CatalystCenterService
from services.catalyst_center.common.exceptions import (
    CatalystCenterNotFoundError,
    CatalystCenterTooManyDevicesError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.version import (
    CatalystCenterRelease,
    installed_version_label,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.device_filters import CatalystCenterDeviceFilters

DEVICES_PATH = "/dna/intent/api/v1/network-device"
# GET /network-device: offset is 1-based, limit 1..500 (same on 2.3.3.x, 2.3.7.x and 3.x).
DEVICE_PAGE_SIZE = 500
_MAX_PAGES = 200
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# keyword -> Intent API query parameter
_FILTER_PARAMS: dict[str, str] = {
    "hostname": "hostname",
    "management_ip": "managementIpAddress",
    "mac_address": "macAddress",
    "family": "family",
    "role": "role",
    "software_type": "softwareType",
    "serial_number": "serialNumber",
    "reachability_status": "reachabilityStatus",
    "platform_id": "platformId",
    "series": "series",
    "device_type": "type",
    "software_version": "softwareVersion",
    "collection_status": "collectionStatus",
}
# Filters that /network-device/count only honours from 2.3.7 on.
_COUNT_FILTERS = frozenset({"hostname", "management_ip", "mac_address"})


def safe_device_id(device_id: str) -> str:
    """Reject ids that could alter the request path."""
    if not isinstance(device_id, str) or not _ID_RE.fullmatch(device_id):
        raise CatalystCenterValidationError("Invalid Catalyst Center device id")
    return device_id


def normalize_device(raw: Any) -> CatalystCenterDevice:
    if not isinstance(raw, dict) or not raw.get("id"):
        raise CatalystCenterValidationError("Catalyst Center device payload has no id")
    return CatalystCenterDevice(
        id=str(raw["id"]),
        hostname=raw.get("hostname"),
        management_ip=raw.get("managementIpAddress"),
        mac_address=raw.get("macAddress"),
        platform_id=raw.get("platformId"),
        family=raw.get("family"),
        device_type=raw.get("type"),
        serial_number=raw.get("serialNumber"),
        software_version=raw.get("softwareVersion"),
        software_type=raw.get("softwareType"),
        role=raw.get("role"),
        reachability_status=raw.get("reachabilityStatus"),
        collection_status=raw.get("collectionStatus"),
        raw=dict(raw),
    )


def _query_params(filters: dict[str, Any]) -> dict[str, Any]:
    unknown = set(filters) - set(_FILTER_PARAMS)
    if unknown:
        raise CatalystCenterValidationError(f"Unsupported device filter: {sorted(unknown)[0]}")
    return {_FILTER_PARAMS[key]: value for key, value in filters.items() if value}


def _response_body(payload: Any) -> Any:
    return payload.get("response") if isinstance(payload, dict) else None


class CatalystCenterDeviceService:
    """Device lookups against one Catalyst Center, hiding release differences."""

    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials
        self._release: CatalystCenterRelease | None = None
        self._release_checked = False

    async def test_connection(self) -> str | None:
        """Authenticate and read ``/dnac-release``; proves URL, TLS and credentials work.

        Returns the version string the controller reports, verbatim (may be a platform
        build rather than a product release), or None if it reports none.
        """
        payload = await self._client.request(self._credentials, "GET", RELEASE_PATH)
        return installed_version_label(payload)

    async def get_device(self, device_id: str) -> CatalystCenterDevice:
        payload = await self._client.request(
            self._credentials, "GET", f"{DEVICES_PATH}/{safe_device_id(device_id)}"
        )
        return normalize_device(_response_body(payload))

    async def find_by_ip(self, ip_address: str) -> CatalystCenterDevice | None:
        try:
            address = str(ipaddress.ip_address(ip_address.strip()))
        except ValueError as exc:
            raise CatalystCenterValidationError("Invalid IP address") from exc
        try:
            payload = await self._client.request(
                self._credentials, "GET", f"{DEVICES_PATH}/ip-address/{address}"
            )
        except CatalystCenterNotFoundError:
            return None
        return normalize_device(_response_body(payload))

    async def find_by_names(self, names: list[str]) -> tuple[CatalystCenterDevice, ...]:
        """Exact hostname match. The API filter is a case-sensitive full match where ``.*`` is
        a wildcard, so a name containing ``.*`` is first narrowed server-side; the exact
        comparison here guards against any such wildcard in the name."""
        seen_names: set[str] = set()
        found: dict[str, CatalystCenterDevice] = {}
        for raw_name in names:
            name = raw_name.strip()
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            for device in await self.list_devices(hostname=name):
                if (device.hostname or "").lower() == name.lower():
                    found.setdefault(device.id, device)
        return tuple(found.values())

    async def list_devices(
        self, *, max_devices: int | None = None, **filters: Any
    ) -> tuple[CatalystCenterDevice, ...]:
        return await self._collect(_query_params(filters), limit=max_devices)

    async def search_devices(
        self, filters: CatalystCenterDeviceFilters, *, max_devices: int | None = None
    ) -> tuple[CatalystCenterDevice, ...]:
        """All devices matching ``filters`` (server-side filters + exact client-side CIDR).

        With ``max_devices`` set, more matches than that raise
        :class:`CatalystCenterTooManyDevicesError` instead of silently truncating.
        """
        if max_devices is not None and (
            isinstance(max_devices, bool) or not isinstance(max_devices, int) or max_devices < 1
        ):
            raise CatalystCenterValidationError("max_devices must be a positive whole number")
        found = await self._collect(
            filters.to_query_params(),
            keep=self._cidr_keep(filters),
            limit=None if max_devices is None else max_devices + 1,
        )
        if max_devices is not None and len(found) > max_devices:
            raise CatalystCenterTooManyDevicesError(max_devices)
        return found

    async def preview_devices(
        self, filters: CatalystCenterDeviceFilters, *, limit: int
    ) -> tuple[tuple[CatalystCenterDevice, ...], bool]:
        """The first ``limit`` matches and whether more exist (fetches ``limit + 1``)."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise CatalystCenterValidationError("limit must be a positive whole number")
        found = await self._collect(
            filters.to_query_params(), keep=self._cidr_keep(filters), limit=limit + 1
        )
        return found[:limit], len(found) > limit

    @staticmethod
    def _cidr_keep(
        filters: CatalystCenterDeviceFilters,
    ) -> Callable[[CatalystCenterDevice], bool] | None:
        if filters.cidr is None:
            return None
        return lambda device: filters.matches_ip(device.management_ip)

    async def _collect(
        self,
        params: dict[str, Any],
        *,
        keep: Callable[[CatalystCenterDevice], bool] | None = None,
        limit: int | None = None,
    ) -> tuple[CatalystCenterDevice, ...]:
        """Page through ``GET /network-device`` keeping devices that pass ``keep``.

        Stops as soon as ``limit`` devices are kept. Raises if the controller never returns a
        short page within ``_MAX_PAGES`` (a runaway list).
        """
        kept: list[CatalystCenterDevice] = []
        for page in range(_MAX_PAGES):
            payload = await self._client.request(
                self._credentials,
                "GET",
                DEVICES_PATH,
                params={**params, "offset": 1 + page * DEVICE_PAGE_SIZE, "limit": DEVICE_PAGE_SIZE},
            )
            body = _response_body(payload)
            if not isinstance(body, list):
                raise CatalystCenterValidationError("Catalyst Center device list was not a list")
            for item in body:
                device = normalize_device(item)
                if keep is not None and not keep(device):
                    continue
                kept.append(device)
                if limit is not None and len(kept) >= limit:
                    return tuple(kept)
            if len(body) < DEVICE_PAGE_SIZE:
                return tuple(kept)
        raise CatalystCenterValidationError("Catalyst Center device list exceeded page bound")

    async def count_devices(self, **filters: Any) -> int:
        params = _query_params(filters)
        if params and not await self._count_endpoint_supports(filters):
            # Older releases only return the unfiltered total: count by listing instead.
            return len(await self.list_devices(**filters))
        payload = await self._client.request(
            self._credentials, "GET", f"{DEVICES_PATH}/count", params=params or None
        )
        count = _response_body(payload)
        if not isinstance(count, int):
            raise CatalystCenterValidationError("Catalyst Center device count was not a number")
        return count

    async def _count_endpoint_supports(self, filters: dict[str, Any]) -> bool:
        active = {key for key, value in filters.items() if value}
        if not active <= _COUNT_FILTERS:
            return False
        release = await self._get_release()
        return release is not None and release.supports_filtered_device_count

    async def _get_release(self) -> CatalystCenterRelease | None:
        """The product release, or None when the controller does not report a usable one.

        An unknown release is treated as "no optional capabilities": callers fall back to
        behaviour that works on every release.
        """
        if not self._release_checked:
            try:
                self._release = await self._client.get_release(self._credentials)
            except CatalystCenterValidationError:
                self._release = None
            self._release_checked = True
        return self._release
