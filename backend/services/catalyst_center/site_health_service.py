"""Site health from Cisco Catalyst Center: ``GET /site-health`` (read-only).

``{"response": [{siteName, siteType, parentSiteName, networkHealthAverage,
numberOfNetworkDevice, networkHealthAccess|Core|Distribution|Router|Switch|AP|WLC|Wireless|Others,
numberOfClients, clientHealthWired, clientHealthWireless, ...}]}``, 1-based ``offset``/``limit``,
``limit`` 1..50, optional ``siteType`` (AREA or BUILDING; there are no floors).

Verified live on the DevNet sandbox (Catalyst Center 3.723): the field names below, ``limit``
max 50, lowercase ``siteType`` in rows, and aggregate rows (``" All Sites"``, ``" All Buildings"``)
that are totals, not sites (``is_total``). Numbers may arrive as strings and are coerced; an
unknown shape is skipped, never guessed. A controller without the endpoint (a 404) surfaces as
``CatalystCenterNotFoundError``.
"""

from __future__ import annotations

from typing import Any

from models.catalyst_center_facts import CatalystCenterSiteHealth
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.coerce import integer, number, text
from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.credentials import CatalystCenterCredentials

SITE_HEALTH_PATH = "/dna/intent/api/v1/site-health"
# The endpoint accepts AREA and BUILDING only (floors are not in /site-health) and limit 1..50.
SITE_TYPES = frozenset({"AREA", "BUILDING"})
PAGE_SIZE = 50
_MAX_PAGES = 40


class CatalystCenterSiteHealthService:
    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials

    async def list_site_health(
        self, *, site_type: str | None = None
    ) -> tuple[CatalystCenterSiteHealth, ...]:
        if site_type is not None and site_type not in SITE_TYPES:
            raise CatalystCenterValidationError(f"site_type must be one of {sorted(SITE_TYPES)}")
        found: list[CatalystCenterSiteHealth] = []
        for page in range(_MAX_PAGES):
            params: dict[str, Any] = {"offset": 1 + page * PAGE_SIZE, "limit": PAGE_SIZE}
            if site_type:
                params["siteType"] = site_type
            payload = await self._client.request(
                self._credentials, "GET", SITE_HEALTH_PATH, params=params
            )
            body = payload.get("response") if isinstance(payload, dict) else None
            if not isinstance(body, list):
                raise CatalystCenterValidationError(
                    "Catalyst Center returned an unexpected site health response"
                )
            found.extend(row for item in body if (row := _normalize(item)) is not None)
            if len(body) < PAGE_SIZE:
                return tuple(found)
        raise CatalystCenterValidationError("Catalyst Center site health exceeded page bound")


def _normalize(raw: Any) -> CatalystCenterSiteHealth | None:
    if not isinstance(raw, dict) or not (name := text(raw.get("siteName"))):
        return None
    site_id = text(raw.get("siteId"))
    return CatalystCenterSiteHealth(
        site_name=name,
        # Verified live (3.723): the aggregate rows are named "All ..." and have an empty siteId
        # or one equal to the name. A real site that lacks a siteId is not a total.
        is_total=site_id == name or (site_id is None and name.lower().startswith("all ")),
        site_type=text(raw.get("siteType")),
        parent_site_name=text(raw.get("parentSiteName")),
        network_health_average=number(raw.get("networkHealthAverage")),
        number_of_network_devices=integer(raw.get("numberOfNetworkDevice")),
        health_access=number(raw.get("networkHealthAccess")),
        health_core=number(raw.get("networkHealthCore")),
        health_distribution=number(raw.get("networkHealthDistribution")),
        health_router=number(raw.get("networkHealthRouter")),
        health_switch=number(raw.get("networkHealthSwitch")),
        health_ap=number(raw.get("networkHealthAP")),
        health_wlc=number(raw.get("networkHealthWLC")),
        health_wireless=number(raw.get("networkHealthWireless")),
        health_others=number(raw.get("networkHealthOthers")),
        number_of_clients=integer(raw.get("numberOfClients")),
        client_health_wired=number(raw.get("clientHealthWired")),
        client_health_wireless=number(raw.get("clientHealthWireless")),
    )
