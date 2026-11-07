"""Find, list and trace the history of endpoints in a Cisco ACI fabric (read-only).

Two reads against the APIC's learned-endpoint objects (``fvCEp``; documented MIT, the DevNet
sandbox could not confirm that it holds any endpoint):

- a MAC address is one ``fvCEp`` query with its children (``fvIp``, ``fvRsCEpToPathEp``);
- an IPv4 address is first found as ``fvIp`` (an endpoint may have several addresses), which
  names its endpoint in the DN, and then those endpoints are read as above.

Addresses are validated before they are placed in a filter, so nothing a user types can alter the
query. Not read: endpoints behind a hypervisor (VMM ``fvRsVm`` / ``fvRsHyper`` relations).

``list_endpoints`` reads the endpoints of one tenant, application profile or EPG. ``history``
reads what the APIC keeps about when an endpoint appeared: the timestamps of the endpoint, of its
addresses and of its record on each leaf, plus the event and fault records that name it. The APIC
keeps no move history, so that is all there is.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Protocol

from models.aci_endpoint import (
    AciEndpoint,
    AciEndpointAttachment,
    AciEndpointEvent,
    AciEndpointHistory,
    AciEndpointIpRecord,
    AciLeafEndpointRecord,
)
from services.aci.common.coerce import text
from services.aci.common.exceptions import AciAPIError, AciError, AciValidationError
from services.aci.common.paths import parse_path
from services.aci.credentials import AciCredentials

# More than this many endpoints for one address fails instead of being truncated.
MAX_MATCHES = 50
# A listing of one tenant or EPG fails (narrow it) beyond this many endpoints.
MAX_LISTED = 2000
# History: events and faults that name the endpoint, per class, newest first.
MAX_EVENTS = 15
MAX_HISTORY_IPS = 5
_SAFE_PART = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
_VRF_DN = re.compile(r"^uni/tn-([^/]+)/ctx-([^/]+)$")
_BD_DN = re.compile(r"^uni/tn-([^/]+)/BD-([^/]+)$")
_ESG_DN = re.compile(r"^uni/tn-([^/]+)/ap-([^/]+)/esg-([^/]+)$")
_EPOCH_YEAR = "1970-"

_MAC_DIGITS = re.compile(r"^[0-9A-F]{12}$")
_CEP_OF_IP = re.compile(r"^(uni/.+/cep-[0-9A-Fa-f:]{17})/ip-\[")
_APP_EPG = re.compile(r"^uni/tn-([^/]+)/ap-([^/]+)/epg-([^/]+)/cep-")
_EXTERNAL_EPG = re.compile(r"^uni/tn-([^/]+)/out-([^/]+)/instP-([^/]+)/cep-")
# The only characters an endpoint DN taken from the APIC may carry into a filter.
_SAFE_DN = re.compile(r"^[A-Za-z0-9_.:\-\[\]/]+$")
_UNSET_IPS = frozenset({"", "0.0.0.0"})  # noqa: S104 - the APIC's "no address", not a bind


class AciEndpointClient(Protocol):
    async def query_class(
        self,
        credentials: AciCredentials,
        class_name: str,
        *,
        query_filter: str | None = None,
        max_objects: int = ...,
    ) -> list[dict[str, Any]]: ...

    async def query_class_tree(
        self,
        credentials: AciCredentials,
        class_name: str,
        *,
        query_filter: str | None = None,
        child_classes: tuple[str, ...] = ...,
        max_objects: int = ...,
    ) -> list[dict[str, Any]]: ...

    async def query_node_class(
        self,
        credentials: AciCredentials,
        pod_id: int,
        node_id: int,
        class_name: str,
        *,
        query_filter: str | None = None,
        max_objects: int = ...,
    ) -> list[dict[str, Any]]: ...

    async def get(
        self, credentials: AciCredentials, path: str, *, params: dict[str, Any] | None = None
    ) -> Any: ...


def normalize_mac(value: str) -> str | None:
    """``0050.56aa.bb01`` / ``00-50-56-aa-bb-01`` / ``005056aabb01`` as ``00:50:56:AA:BB:01``."""
    digits = re.sub(r"[:.\-]", "", value.strip()).upper()
    if not _MAC_DIGITS.match(digits):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def _ipv4(value: str) -> str | None:
    try:
        return str(ipaddress.IPv4Address(value.strip()))
    except ValueError:
        return None


class AciEndpointService:
    """Read-only endpoint lookups for one APIC source (credentials already resolved)."""

    def __init__(self, client: AciEndpointClient, credentials: AciCredentials) -> None:
        self._client = client
        self._credentials = credentials

    async def find(self, address: str) -> tuple[AciEndpoint, ...]:
        """The endpoints that own an IPv4 or MAC address; empty when the fabric does not know it."""
        return _endpoints(await self._rows_for(address))

    async def list_endpoints(
        self, *, tenant: str, app_profile: str | None = None, epg: str | None = None
    ) -> tuple[AciEndpoint, ...]:
        """The learned endpoints of a tenant, of one application profile or of one EPG.

        Fails with ``too_many_objects`` beyond ``MAX_LISTED`` (narrow to an EPG) rather than
        truncating. The names go into a filter, so they must be plain ACI names.
        """
        if epg is not None and app_profile is None:
            raise AciValidationError("An EPG needs its application profile")
        for value in (tenant, app_profile, epg):
            if value is not None and not _SAFE_PART.match(value):
                raise AciValidationError("A tenant, profile or EPG name has unsupported characters")
        needle = f"/tn-{tenant}/"
        if app_profile is not None:
            needle += f"ap-{app_profile}/"
        if epg is not None:
            needle += f"epg-{epg}/"
        rows = await self._client.query_class_tree(
            self._credentials,
            "fvCEp",
            query_filter=f'wcard(fvCEp.dn,"{needle}")',
            child_classes=("fvIp", "fvRsCEpToPathEp"),
            max_objects=MAX_LISTED,
        )
        return _endpoints(rows)

    async def history(self, address: str) -> tuple[AciEndpointHistory, ...]:
        """Timestamps of the endpoint(s) of an address, plus the log lines that name them."""
        histories = []
        for row in await self._rows_for(address):
            if (endpoint := _endpoint(row)) is not None:
                histories.append(await self._history_of(endpoint, row))
        return tuple(histories)

    async def _rows_for(self, address: str) -> list[dict[str, Any]]:
        mac = normalize_mac(address)
        if mac is not None:
            return await self._read_rows([f'eq(fvCEp.mac,"{mac}")'])
        ip = _ipv4(address)
        if ip is None:
            raise AciValidationError("Not an IPv4 or MAC address")
        rows = await self._client.query_class(
            self._credentials,
            "fvIp",
            query_filter=f'eq(fvIp.addr,"{ip}")',
            max_objects=MAX_MATCHES,
        )
        dns = sorted(
            {m.group(1) for row in rows if (m := _CEP_OF_IP.match(text(row.get("dn")) or ""))}
        )
        if not dns:
            return []
        if len(dns) > MAX_MATCHES:
            raise AciAPIError(
                f"More than {MAX_MATCHES} endpoints use {ip}", code="too_many_objects"
            )
        if not all(_SAFE_DN.match(dn) for dn in dns):
            # Never build a filter from a DN with unexpected characters, and never answer "not
            # learned" for an address the fabric did report: fail the lookup instead.
            raise AciAPIError(
                "The APIC returned an endpoint name this tool cannot query safely",
                code="unsafe_endpoint_dn",
            )
        return await self._read_rows([f'eq(fvCEp.dn,"{dn}")' for dn in dns])

    async def _read_rows(self, conditions: list[str]) -> list[dict[str, Any]]:
        if not conditions:
            return []
        query_filter = conditions[0] if len(conditions) == 1 else f"or({','.join(conditions)})"
        return await self._client.query_class_tree(
            self._credentials,
            "fvCEp",
            query_filter=query_filter,
            child_classes=("fvIp", "fvRsCEpToPathEp"),
            max_objects=MAX_MATCHES,
        )

    async def _history_of(self, endpoint: AciEndpoint, row: dict[str, Any]) -> AciEndpointHistory:
        attributes = row.get("attributes") or {}
        children = row.get("children") or {}
        ips = sorted(
            (
                AciEndpointIpRecord(
                    address=address,
                    learned_at=_stamp(child.get("createTs")),
                    last_changed=_stamp(child.get("modTs")),
                )
                for child in children.get("fvIp", [])
                if (address := text(child.get("addr"))) and address not in _UNSET_IPS
            ),
            key=lambda r: r.address,
        )
        nodes = sorted({(a.pod_id, node) for a in endpoint.attachments for node in a.node_ids})
        leaf_records, failed = await self._leaf_records(endpoint.mac, nodes)
        events, unavailable = await self._events(endpoint.mac, [r.address for r in ips])
        return AciEndpointHistory(
            mac=endpoint.mac,
            tenant=endpoint.tenant,
            app_profile=endpoint.app_profile,
            epg=endpoint.epg,
            external_epg=endpoint.external_epg,
            last_changed=_stamp(attributes.get("modTs")),
            ips=tuple(ips),
            leaf_records=leaf_records,
            events=events,
            leaf_records_failed=failed,
            events_unavailable=unavailable,
        )

    async def _leaf_records(
        self, mac: str, nodes: list[tuple[int, int]]
    ) -> tuple[tuple[AciLeafEndpointRecord, ...], int]:
        """The endpoint's record on each leaf it is attached to; a leaf that fails is counted."""
        records: list[AciLeafEndpointRecord] = []
        failed = 0
        for pod_id, node_id in nodes:
            try:
                found = await self._client.query_node_class(
                    self._credentials,
                    pod_id,
                    node_id,
                    "epmMacEp",
                    query_filter=f'eq(epmMacEp.addr,"{mac}")',
                    max_objects=20,
                )
            except AciError:
                failed += 1
                continue
            records.extend(
                AciLeafEndpointRecord(
                    pod_id=pod_id,
                    node_id=node_id,
                    interface=text(row.get("ifId")),
                    first_seen=_stamp(row.get("createTs")),
                    last_changed=_stamp(row.get("modTs")),
                    flags=text(row.get("flags")),
                )
                for row in found
            )
        return tuple(records), failed

    async def _events(
        self, mac: str, addresses: list[str]
    ) -> tuple[tuple[AciEndpointEvent, ...], bool]:
        """Event and fault records that name the MAC or an address (values are validated)."""
        needles = [mac, *addresses[:MAX_HISTORY_IPS]]
        found: list[AciEndpointEvent] = []
        try:
            for cls, kind, fields in (
                ("eventRecord", "event", ("affected", "descr")),
                ("faultRecord", "fault", ("affected", "descr")),
            ):
                terms = [f'wcard({cls}.{f},"{n}")' for n in needles for f in fields]
                answer = await self._client.get(
                    self._credentials,
                    f"/api/class/{cls}.json",
                    params={
                        "query-target-filter": f"or({','.join(terms)})",
                        "order-by": f"{cls}.created|desc",
                        "page": 0,
                        "page-size": MAX_EVENTS,
                    },
                )
                for item in (answer.get("imdata") if isinstance(answer, dict) else None) or []:
                    attrs = (next(iter(item.values()), {}) or {}).get("attributes") or {}
                    found.append(
                        AciEndpointEvent(
                            kind=kind,  # type: ignore[arg-type]
                            time=_stamp(attrs.get("created")),
                            code=text(attrs.get("code")),
                            severity=text(attrs.get("severity")),
                            description=text(attrs.get("descr")),
                        )
                    )
        except AciError:
            return tuple(found), True
        found.sort(key=lambda e: e.time or "", reverse=True)
        return tuple(found[: MAX_EVENTS * 2]), False


def _stamp(value: Any) -> str | None:
    """An APIC timestamp, or ``None`` when it is unset (the epoch some objects report)."""
    stamp = text(value)
    return None if stamp is None or stamp.startswith(_EPOCH_YEAR) else stamp


def _name(pattern: re.Pattern[str], value: Any) -> str | None:
    match = pattern.match(text(value) or "")
    return "/".join(match.groups()) if match else None


def _endpoints(rows: list[dict[str, Any]]) -> tuple[AciEndpoint, ...]:
    endpoints = [_endpoint(row) for row in rows]
    return tuple(
        sorted((e for e in endpoints if e is not None), key=lambda e: (e.mac, e.tenant or ""))
    )


def _endpoint(row: dict[str, Any]) -> AciEndpoint | None:
    attributes = row.get("attributes") or {}
    children = row.get("children") or {}
    mac = normalize_mac(text(attributes.get("mac")) or "")
    if mac is None:
        return None
    dn = text(attributes.get("dn")) or ""
    tenant = app_profile = epg = external = None
    if match := _APP_EPG.match(dn):
        tenant, app_profile, epg = match.groups()
    elif match := _EXTERNAL_EPG.match(dn):
        tenant, external = match.group(1), f"{match.group(2)}/{match.group(3)}"

    addresses = {text(c.get("addr")) for c in children.get("fvIp", [])}
    addresses.add(text(attributes.get("ip")))
    ips = sorted(a for a in addresses if a and a not in _UNSET_IPS)
    attachments = [
        AciEndpointAttachment(pod_id=p.pod_id, node_ids=p.node_ids, interface=p.interface)
        for child in children.get("fvRsCEpToPathEp", [])
        if (p := parse_path(text(child.get("tDn")))) is not None
    ]
    return AciEndpoint(
        mac=mac,
        ips=tuple(ips),
        tenant=tenant,
        app_profile=app_profile,
        epg=epg,
        external_epg=external,
        encap=text(attributes.get("encap")),
        vrf=_name(_VRF_DN, attributes.get("vrfDn")),
        bridge_domain=_name(_BD_DN, attributes.get("bdDn")),
        esg=_name(_ESG_DN, attributes.get("esgUsegDn")),
        attachments=tuple(sorted(attachments, key=lambda a: (a.pod_id, a.node_ids, a.interface))),
    )
