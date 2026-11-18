"""SD-Access fabric membership from Cisco Catalyst Center (read-only).

Overlay members are the devices that hold a fabric role (border, control plane, edge, ...) in a
fabric site. Underlay members are those same devices plus the intermediate nodes of the fabric
sites' hierarchy that hold no fabric role. Endpoints (the current ``/sda`` family, not the
legacy ``/business/sda`` one that needs a device address per call):

- ``GET /sda/fabricSites``: ``{"response": [{id, siteId, ...}]}`` (fabric id, site id)
- ``GET /sda/fabricDevices?fabricId=``: ``{"response": [{networkDeviceId, deviceRoles, ...}]}``
- ``GET /sda/layer3VirtualNetworks``: ``{"response": [{virtualNetworkName, fabricIds}]}``

Field names are taken from the Cisco API reference and are **not yet verified live**
(doc/CISCO_CATALYST_INTEGRATION.md). Unknown shapes are skipped, never guessed.
"""

from __future__ import annotations

import logging
from typing import Any

from models.catalyst_center import CatalystCenterSite
from models.catalyst_center_facts import (
    CatalystCenterFabric,
    CatalystCenterFabricDevice,
    CatalystCenterFabricSite,
    CatalystCenterUnderlayDevice,
    CatalystCenterVirtualNetwork,
)
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.coerce import text
from services.catalyst_center.common.exceptions import (
    CatalystCenterNotFoundError,
    CatalystCenterTooManySitesError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.ids import safe_device_id
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.site_service import CatalystCenterSiteService

_SDA = "/dna/intent/api/v1/sda"
FABRIC_SITES_PATH = f"{_SDA}/fabricSites"
FABRIC_DEVICES_PATH = f"{_SDA}/fabricDevices"
VIRTUAL_NETWORKS_PATH = f"{_SDA}/layer3VirtualNetworks"
logger = logging.getLogger(__name__)
PAGE_SIZE = 500
_MAX_PAGES = 50
MAX_FABRIC_SITES = 100


class CatalystCenterFabricService:
    """Fabric sites, fabric devices and virtual networks of one Catalyst Center."""

    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials
        self._sites = CatalystCenterSiteService(client, credentials)

    async def read_fabric(
        self, *, include_underlay: bool = False, fabric_site: str | None = None
    ) -> CatalystCenterFabric:
        """The fabric; with ``include_underlay`` also the fabric sites' role-less devices.

        ``fabric_site`` (an exact hierarchy name) limits the per-site reads (devices, membership)
        to that fabric site; the site list and the virtual networks stay whole. A fabric site
        whose devices cannot be read completely is named in ``incomplete_sites`` instead of
        failing the answer. Only a missing fabric-site list (no SD-Access API) raises.
        """
        sites = await self._sites.list_sites()
        site_names = {site.id: site.name_hierarchy for site in sites}
        fabric_sites = tuple(
            CatalystCenterFabricSite(
                fabric_id=fabric_id,
                site_id=site_id,
                site_name=site_names.get(site_id) if site_id else None,
            )
            for raw in await self._pages(FABRIC_SITES_PATH, {})
            if (fabric_id := text(raw.get("id")))
            and (site_id := text(raw.get("siteId"))) is not None
        )
        if len(fabric_sites) > MAX_FABRIC_SITES:
            raise CatalystCenterValidationError(
                f"The controller has {len(fabric_sites)} fabric sites (limit {MAX_FABRIC_SITES})"
            )
        by_fabric = {site.fabric_id: site.site_name for site in fabric_sites}
        walk = tuple(s for s in fabric_sites if fabric_site is None or s.site_name == fabric_site)

        devices: list[CatalystCenterFabricDevice] = []
        incomplete: list[str] = []
        for site in walk:
            try:
                rows = await self._pages(FABRIC_DEVICES_PATH, {"fabricId": site.fabric_id})
            except CatalystCenterNotFoundError:
                incomplete.append(site.site_name or site.fabric_id)
                continue
            devices.extend(d for raw in rows if (d := _normalize_device(raw, site)) is not None)

        try:
            network_rows = await self._pages(VIRTUAL_NETWORKS_PATH, {})
        except CatalystCenterNotFoundError:
            network_rows = []  # context only: the membership answer must survive its absence
        networks = tuple(
            network for raw in network_rows if (network := _normalize_network(raw, by_fabric))
        )
        underlay: tuple[CatalystCenterUnderlayDevice, ...] = ()
        if include_underlay:
            underlay = await self._underlay_only(walk, devices, sites, incomplete)
        return CatalystCenterFabric(
            sites=fabric_sites,
            devices=tuple(devices),
            virtual_networks=networks,
            underlay_only=underlay,
            incomplete_sites=tuple(dict.fromkeys(incomplete)),
        )

    async def _underlay_only(
        self,
        fabric_sites: tuple[CatalystCenterFabricSite, ...],
        devices: list[CatalystCenterFabricDevice],
        sites: tuple[CatalystCenterSite, ...],
        incomplete: list[str],
    ) -> tuple[CatalystCenterUnderlayDevice, ...]:
        """Members of each fabric site's hierarchy that hold no fabric role.

        A device under nested fabric sites belongs to the most specific one (longest name), so
        the answer does not depend on the order the controller lists the sites in. A site whose
        hierarchy is too large to read is reported in ``incomplete``, not raised.
        """
        with_role = {device.device_id for device in devices}
        owner: dict[str, str] = {}
        for site in fabric_sites:
            if not site.site_name:
                continue
            try:
                members = await self._sites.device_ids_for_sites([site.site_name], sites=sites)
            except CatalystCenterTooManySitesError:
                incomplete.append(site.site_name)
                continue
            for device_id in members - with_role:
                if len(site.site_name) > len(owner.get(device_id, "")):
                    owner[device_id] = site.site_name
        found: list[CatalystCenterUnderlayDevice] = []
        for device_id in sorted(owner):
            try:
                found.append(
                    CatalystCenterUnderlayDevice(
                        device_id=safe_device_id(device_id), fabric_site=owner[device_id]
                    )
                )
            except CatalystCenterValidationError:
                # An id in an unexpected form is skipped, not fatal (log the count only).
                logger.debug("Catalyst Center membership id skipped: not a plain id")
        return tuple(found)

    async def _pages(self, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """All records of a paged ``{"response": [...]}`` list (1-based offset)."""
        records: list[dict[str, Any]] = []
        for page in range(_MAX_PAGES):
            payload = await self._client.request(
                self._credentials,
                "GET",
                path,
                params={**params, "offset": 1 + page * PAGE_SIZE, "limit": PAGE_SIZE},
            )
            body = payload.get("response") if isinstance(payload, dict) else None
            if not isinstance(body, list):
                raise CatalystCenterValidationError(
                    "Catalyst Center returned an unexpected SD-Access response"
                )
            records.extend(item for item in body if isinstance(item, dict))
            if len(body) < PAGE_SIZE:
                return records
        raise CatalystCenterValidationError("Catalyst Center SD-Access list exceeded page bound")


def _valid_id(value: str) -> bool:
    try:
        safe_device_id(value)
    except CatalystCenterValidationError:
        return False
    return True


def _normalize_device(
    raw: dict[str, Any], site: CatalystCenterFabricSite
) -> CatalystCenterFabricDevice | None:
    device_id = text(raw.get("networkDeviceId"))
    roles = raw.get("deviceRoles")
    if not device_id or not isinstance(roles, list) or not _valid_id(device_id):
        return None  # an id the inventory join would reject is skipped here, not fatal later
    return CatalystCenterFabricDevice(
        device_id=device_id,
        fabric_id=site.fabric_id,
        fabric_site=site.site_name,
        roles=tuple(sorted({role for item in roles if (role := text(item))})),
    )


def _normalize_network(
    raw: dict[str, Any], site_by_fabric: dict[str, str | None]
) -> CatalystCenterVirtualNetwork | None:
    name = text(raw.get("virtualNetworkName"))
    if not name:
        return None
    fabric_ids = raw.get("fabricIds")
    names = {
        site
        for fabric_id in (fabric_ids if isinstance(fabric_ids, list) else [])
        if (site := site_by_fabric.get(str(fabric_id)))
    }
    return CatalystCenterVirtualNetwork(name=name, fabric_sites=tuple(sorted(names)))
