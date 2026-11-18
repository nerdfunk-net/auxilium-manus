"""Border nodes and their handoffs to the legacy network, from Catalyst Center (read-only).

- ``GET /sda/fabricDevices?fabricId=&deviceRoles=BORDER_NODE``: the border nodes of a fabric site
- ``GET /sda/transitNetworks``: transit definitions (``id`` -> name, type)
- ``GET /sda/fabricDevices/layer3Handoffs/ipTransits?fabricId=&networkDeviceId=``
- ``GET /sda/fabricDevices/layer3Handoffs/sdaTransits?fabricId=&networkDeviceId=``
- ``GET /sda/fabricDevices/layer2Handoffs?fabricId=&networkDeviceId=``

The paths and their query parameters were checked on the DevNet sandbox (Catalyst Center 3.723,
no fabric: every list was empty). The **row field names** come from the Cisco API reference and
are **not verified live**; a row with none of the expected fields is skipped, never guessed, and a
kind whose rows were all unrecognised is listed in ``unavailable``. A kind the controller answers
with an error for one border is listed in ``unavailable`` too, instead of failing the rest.
"""

from __future__ import annotations

from typing import Any

from models.catalyst_center_facts import (
    CatalystCenterBorderHandoffs,
    CatalystCenterFabricDevice,
    CatalystCenterIpTransitHandoff,
    CatalystCenterLayer2Handoff,
    CatalystCenterSdaTransitHandoff,
    CatalystCenterTransit,
)
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.coerce import boolean, integer, text
from services.catalyst_center.common.exceptions import (
    CatalystCenterError,
    CatalystCenterNotFoundError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.ids import safe_device_id
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.fabric_service import CatalystCenterFabricService
from services.catalyst_center.sda_pages import read_sda_pages

_SDA = "/dna/intent/api/v1/sda"
TRANSITS_PATH = f"{_SDA}/transitNetworks"
IP_TRANSITS_PATH = f"{_SDA}/fabricDevices/layer3Handoffs/ipTransits"
SDA_TRANSITS_PATH = f"{_SDA}/fabricDevices/layer3Handoffs/sdaTransits"
LAYER2_HANDOFFS_PATH = f"{_SDA}/fabricDevices/layer2Handoffs"
BORDER_ROLE = "BORDER_NODE"


class CatalystCenterBorderService:
    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials
        self._fabric = CatalystCenterFabricService(client, credentials)

    async def list_borders(
        self, *, fabric_site: str | None = None
    ) -> tuple[tuple[CatalystCenterFabricDevice, ...], tuple[str, ...]]:
        """Border nodes (those holding ``BORDER_NODE``) and the fabric sites that failed to read."""
        fabric = await self._fabric.read_fabric(fabric_site=fabric_site, include_networks=False)
        borders = tuple(d for d in fabric.devices if BORDER_ROLE in d.roles)
        return borders, fabric.incomplete_sites

    async def list_transits(self, *, missing_ok: bool = True) -> dict[str, CatalystCenterTransit]:
        """Transit definitions by id. A controller without the API gives ``{}`` when ``missing_ok``
        (context for handoff names), else ``CatalystCenterNotFoundError``."""
        try:
            rows = await read_sda_pages(self._client, self._credentials, TRANSITS_PATH, {})
        except CatalystCenterNotFoundError:
            if not missing_ok:
                raise
            return {}
        out: dict[str, CatalystCenterTransit] = {}
        for raw in rows:
            transit = _transit_network(raw)
            if transit is not None:
                out[transit.id] = transit
        return out

    async def read_handoffs(
        self, border: CatalystCenterFabricDevice, transits: dict[str, CatalystCenterTransit]
    ) -> CatalystCenterBorderHandoffs:
        unavailable: list[str] = []

        async def rows(kind: str, path: str) -> list[dict[str, Any]]:
            # Any controller-side failure of one kind is that kind's "unavailable", not the page's.
            try:
                params = {
                    "fabricId": safe_device_id(border.fabric_id),
                    "networkDeviceId": safe_device_id(border.device_id),
                }
                return await read_sda_pages(self._client, self._credentials, path, params)
            except CatalystCenterError, TimeoutError, OSError:
                unavailable.append(kind)
                return []

        def keep(
            kind: str, raw_rows: list[dict[str, Any]], items: tuple[Any, ...]
        ) -> tuple[Any, ...]:
            if raw_rows and not items:  # rows came back but none had a known field
                unavailable.append(kind)
            return items

        ip_rows = await rows("ip_transits", IP_TRANSITS_PATH)
        sda_rows = await rows("sda_transits", SDA_TRANSITS_PATH)
        l2_rows = await rows("layer2", LAYER2_HANDOFFS_PATH)
        ip_items = tuple(h for r in ip_rows if (h := _ip_transit(r, transits)) is not None)
        sda_items = tuple(h for r in sda_rows if (h := _sda_transit(r, transits)) is not None)
        l2_items = tuple(h for r in l2_rows if (h := _layer2(r)) is not None)
        return CatalystCenterBorderHandoffs(
            device_id=border.device_id,
            ip_transits=keep("ip_transits", ip_rows, ip_items),
            sda_transits=keep("sda_transits", sda_rows, sda_items),
            layer2=keep("layer2", l2_rows, l2_items),
            unavailable=tuple(dict.fromkeys(unavailable)),
        )


def _transit_network(raw: dict[str, Any]) -> CatalystCenterTransit | None:
    # Field names from the Cisco API reference (ipTransitSettings, sdaTransitSettings); the
    # sandbox has no transit, so they are not verified live.
    transit_id = text(raw.get("id"))
    if not transit_id:
        return None
    ip_settings = raw.get("ipTransitSettings")
    sda_settings = raw.get("sdaTransitSettings")
    ip_settings = ip_settings if isinstance(ip_settings, dict) else {}
    sda_settings = sda_settings if isinstance(sda_settings, dict) else {}
    devices = sda_settings.get("controlPlaneNetworkDeviceIds")
    return CatalystCenterTransit(
        id=transit_id,
        name=text(raw.get("name")),
        transit_type=text(raw.get("type")),
        routing_protocol=text(ip_settings.get("routingProtocolName")),
        autonomous_system_number=text(ip_settings.get("autonomousSystemNumber")),
        multicast_over_transit=boolean(sda_settings.get("isMulticastOverTransitEnabled")),
        control_plane_device_ids=tuple(
            device_id
            for item in (devices if isinstance(devices, list) else [])
            if (device_id := text(item)) and _valid_id(device_id)
        ),
    )


def _valid_id(value: str) -> bool:
    try:
        safe_device_id(value)
    except CatalystCenterValidationError:
        return False
    return True


def _transit(raw: dict[str, Any], transits: dict[str, CatalystCenterTransit]) -> tuple[Any, Any]:
    transit_id = text(raw.get("transitNetworkId"))
    known = transits.get(transit_id) if transit_id else None
    return transit_id, known.name if known else None


def _has_data(handoff: Any, derived: set[str]) -> bool:
    """False for a row none of whose own fields was recognised (``derived`` ones do not count)."""
    return bool(handoff.model_dump(exclude_none=True, exclude=derived))


def _ip_transit(
    raw: dict[str, Any], transits: dict[str, CatalystCenterTransit]
) -> CatalystCenterIpTransitHandoff | None:
    transit_id, name = _transit(raw, transits)
    handoff = CatalystCenterIpTransitHandoff(
        transit_id=transit_id,
        transit_name=name,
        interface_name=text(raw.get("interfaceName")),
        virtual_network=text(raw.get("virtualNetworkName")),
        vlan_id=integer(raw.get("vlanId")),
        ip_pool=text(raw.get("externalConnectivityIpPoolName")),
        local_ip=text(raw.get("localIpAddress")),
        remote_ip=text(raw.get("remoteIpAddress")),
        local_ipv6=text(raw.get("localIpv6Address")),
        remote_ipv6=text(raw.get("remoteIpv6Address")),
    )
    return handoff if _has_data(handoff, {"transit_name"}) else None


def _sda_transit(
    raw: dict[str, Any], transits: dict[str, CatalystCenterTransit]
) -> CatalystCenterSdaTransitHandoff | None:
    transit_id, name = _transit(raw, transits)
    handoff = CatalystCenterSdaTransitHandoff(
        transit_id=transit_id,
        transit_name=name,
        connected_to_internet=boolean(raw.get("connectedToInternet")),
        multicast_over_transit=boolean(raw.get("isMulticastOverTransitEnabled")),
    )
    return handoff if _has_data(handoff, {"transit_name"}) else None


def _layer2(raw: dict[str, Any]) -> CatalystCenterLayer2Handoff | None:
    handoff = CatalystCenterLayer2Handoff(
        interface_name=text(raw.get("interfaceName")),
        internal_vlan_id=integer(raw.get("internalVlanId")),
        external_vlan_id=integer(raw.get("externalVlanId")),
    )
    return handoff if _has_data(handoff, set()) else None
