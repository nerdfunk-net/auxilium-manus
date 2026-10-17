"""Sites and site membership for Cisco Catalyst Center.

The device list (``GET /network-device``) has no usable site filter, so a site selection is
resolved to device ids through two endpoints present on every release line we support
(2.3.3.x, 2.3.7.x, 3.x):

- ``GET /site``                  -> the site hierarchy (``siteNameHierarchy``, e.g. ``Global/EMEA``)
- ``GET /membership/{siteId}``   -> ``{"site": ..., "device": [{"response": [records]}]}``

Behaviour verified live on the DevNet sandbox (see doc/CISCO_CATALYST_INTEGRATION.md):
membership pages with 1-based ``offset``/``limit``; a device record's id is ``instanceUuid``
(the same UUID the device list calls ``id``); an invalid site id is reported as **HTTP 200**
with an ``errorCode`` body (not an error status), and ``GET /site?name=<unknown>`` returns a
500 — so site names are validated against the real site list instead of being passed through.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any

from models.catalyst_center import CatalystCenterSite
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.ids import safe_device_id
from services.catalyst_center.credentials import CatalystCenterCredentials

SITE_PATH = "/dna/intent/api/v1/site"
MEMBERSHIP_PATH = "/dna/intent/api/v1/membership"
SITE_PAGE_SIZE = 500
_MAX_PAGES = 100
# A parent site with children can fan out into many membership calls; refuse absurd selections.
MAX_TARGET_SITES = 100
_MEMBERSHIP_CONCURRENCY = 5


class CatalystCenterSiteService:
    """Site list and site -> device id resolution for one Catalyst Center."""

    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials

    async def list_sites(self) -> tuple[CatalystCenterSite, ...]:
        found: dict[str, CatalystCenterSite] = {}
        for page in range(_MAX_PAGES):
            payload = await self._client.request(
                self._credentials,
                "GET",
                SITE_PATH,
                params={"offset": 1 + page * SITE_PAGE_SIZE, "limit": SITE_PAGE_SIZE},
            )
            body = payload.get("response") if isinstance(payload, dict) else None
            if not isinstance(body, list):
                raise CatalystCenterValidationError("Catalyst Center site list was not a list")
            added = 0
            for item in body:
                site = _normalize_site(item)
                if site is not None and site.id not in found:
                    found[site.id] = site
                    added += 1
            if len(body) < SITE_PAGE_SIZE or added == 0:
                return tuple(found.values())
        raise CatalystCenterValidationError("Catalyst Center site list exceeded page bound")

    async def device_ids_for_sites(
        self, names: Iterable[str], *, include_children: bool = True
    ) -> frozenset[str]:
        """Ids of every device assigned to the named sites (and, optionally, their sub-sites).

        ``names`` are exact ``siteNameHierarchy`` values; an unknown name is a validation
        error. Children are found by name-path prefix (``Global/EMEA`` -> ``Global/EMEA/...``,
        never ``Global/EMEAX``), so the result does not depend on whether the controller's
        membership call is itself recursive.
        """
        requested = list(dict.fromkeys(names))
        if not requested:
            return frozenset()

        sites = await self.list_sites()
        by_name = {site.name_hierarchy: site for site in sites}
        for name in requested:
            if name not in by_name:
                raise CatalystCenterValidationError(
                    f"Unknown site '{name}'; use Search sites to pick an existing one"
                )

        targets: dict[str, CatalystCenterSite] = {}
        for name in requested:
            targets[by_name[name].id] = by_name[name]
            if include_children:
                prefix = name + "/"
                for site in sites:
                    if site.name_hierarchy.startswith(prefix):
                        targets[site.id] = site
        if len(targets) > MAX_TARGET_SITES:
            raise CatalystCenterValidationError(
                f"The selection covers {len(targets)} sites (limit {MAX_TARGET_SITES}); "
                "choose a narrower site"
            )

        semaphore = asyncio.Semaphore(_MEMBERSHIP_CONCURRENCY)

        async def members(site: CatalystCenterSite) -> frozenset[str]:
            async with semaphore:
                return await self._membership_device_ids(site.id)

        results = await asyncio.gather(*(members(site) for site in targets.values()))
        return frozenset().union(*results)

    async def _membership_device_ids(self, site_id: str) -> frozenset[str]:
        path = f"{MEMBERSHIP_PATH}/{safe_device_id(site_id)}"
        ids: set[str] = set()
        for page in range(_MAX_PAGES):
            payload = await self._client.request(
                self._credentials,
                "GET",
                path,
                params={"offset": 1 + page * SITE_PAGE_SIZE, "limit": SITE_PAGE_SIZE},
            )
            page_ids, count = _device_ids_from_membership(payload)
            before = len(ids)
            ids.update(page_ids)
            if count < SITE_PAGE_SIZE or len(ids) == before:
                return frozenset(ids)
        raise CatalystCenterValidationError("Catalyst Center site membership exceeded page bound")


def _normalize_site(raw: Any) -> CatalystCenterSite | None:
    if not isinstance(raw, dict):
        return None
    site_id, hierarchy = raw.get("id"), raw.get("siteNameHierarchy")
    if (
        not isinstance(site_id, str)
        or not site_id
        or not isinstance(hierarchy, str)
        or not hierarchy
    ):
        return None
    name = raw.get("name")
    return CatalystCenterSite(
        id=site_id,
        name=name if isinstance(name, str) and name else hierarchy.rsplit("/", 1)[-1],
        name_hierarchy=hierarchy,
    )


def _device_ids_from_membership(payload: Any) -> tuple[list[str], int]:
    """Device ids on one membership page, and how many device records the page held."""
    blocks = payload.get("device") if isinstance(payload, dict) else None
    if not isinstance(blocks, list):
        raise CatalystCenterAPIError("Catalyst Center site membership response was not valid")
    ids: list[str] = []
    count = 0
    for block in blocks:
        records = block.get("response") if isinstance(block, dict) else None
        if isinstance(records, dict):
            # An invalid request is reported as HTTP 200 with an errorCode body.
            raise CatalystCenterAPIError("Catalyst Center rejected the site membership request")
        if not isinstance(records, list):
            raise CatalystCenterAPIError("Catalyst Center site membership response was not valid")
        for record in records:
            count += 1
            device_id = (
                record.get("instanceUuid") or record.get("id") if isinstance(record, dict) else None
            )
            if isinstance(device_id, str) and device_id:
                ids.append(device_id)
    return ids, count
