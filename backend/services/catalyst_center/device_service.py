"""Version-agnostic device inventory access for Cisco Catalyst Center."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from models.catalyst_center import CatalystCenterDevice, CatalystCenterSite
from services.catalyst_center.client import RELEASE_PATH, CatalystCenterService
from services.catalyst_center.common.exceptions import (
    CatalystCenterTooManyDevicesError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.ids import safe_device_id
from services.catalyst_center.common.version import installed_version_label
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.device_filters import CatalystCenterDeviceFilters
from services.catalyst_center.site_service import CatalystCenterSiteService

DEVICES_PATH = "/dna/intent/api/v1/network-device"
# GET /network-device: offset is 1-based, limit 1..500 (same on 2.3.3.x, 2.3.7.x and 3.x).
DEVICE_PAGE_SIZE = 500
_MAX_PAGES = 200
_ID_CHUNK = 50  # ids per `GET /network-device?id=a,b,c` request (keeps the URL short)


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


def _response_body(payload: Any) -> Any:
    return payload.get("response") if isinstance(payload, dict) else None


class CatalystCenterDeviceService:
    """Device lookups against one Catalyst Center."""

    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials
        self._sites = CatalystCenterSiteService(client, credentials)

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
        found = await self._select(filters, limit=None if max_devices is None else max_devices + 1)
        if max_devices is not None and len(found) > max_devices:
            raise CatalystCenterTooManyDevicesError(max_devices)
        return found

    async def preview_devices(
        self, filters: CatalystCenterDeviceFilters, *, limit: int
    ) -> tuple[tuple[CatalystCenterDevice, ...], bool]:
        """The first ``limit`` matches and whether more exist (fetches ``limit + 1``)."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise CatalystCenterValidationError("limit must be a positive whole number")
        found = await self._select(filters, limit=limit + 1)
        return found[:limit], len(found) > limit

    async def list_sites(self) -> tuple[CatalystCenterSite, ...]:
        """The controller's configured sites (for the site picker)."""
        return await self._sites.list_sites()

    async def _select(
        self, filters: CatalystCenterDeviceFilters, *, limit: int | None
    ) -> tuple[CatalystCenterDevice, ...]:
        """Devices matching ``filters``, resolving a site selection when one is set.

        - no site: ordinary server-side filtered listing (+ exact client-side CIDR);
        - site + other filters: the server narrows by those filters and results are
          intersected with the site's member ids client-side (never relies on how the
          controller combines ``id=`` with other filters);
        - site only: fetch exactly the member devices by id in chunks.
        An empty member set returns nothing without querying (an empty ``id`` would list all).
        """
        cidr_keep = self._cidr_keep(filters)
        if not filters.sites:
            return await self._collect(filters.to_query_params(), keep=cidr_keep, limit=limit)

        member_ids = await self._sites.device_ids_for_sites(
            filters.sites, include_children=filters.include_child_sites
        )
        if not member_ids:
            return ()

        if filters.has_server_filters:
            return await self._collect(
                filters.to_query_params(),
                keep=lambda device: (
                    device.id in member_ids and (cidr_keep is None or cidr_keep(device))
                ),
                limit=limit,
            )
        return await self._collect_by_ids(sorted(member_ids), keep=cidr_keep, limit=limit)

    async def _collect_by_ids(
        self,
        ids: list[str],
        *,
        keep: Callable[[CatalystCenterDevice], bool] | None,
        limit: int | None,
    ) -> tuple[CatalystCenterDevice, ...]:
        kept: list[CatalystCenterDevice] = []
        for start in range(0, len(ids), _ID_CHUNK):
            chunk = ids[start : start + _ID_CHUNK]
            payload = await self._client.request(
                self._credentials,
                "GET",
                DEVICES_PATH,
                params={"id": ",".join(safe_device_id(device_id) for device_id in chunk)},
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
        return tuple(kept)

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
