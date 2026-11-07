"""Gateway subnets of a Cisco ACI fabric (read-only).

Fabric-wide class queries (``GET /api/class/<Class>.json``): ``fvSubnet`` (the gateway address with
its mask, under a bridge domain ``BD-<name>`` or an EPG), ``fvRsCtx`` (the bridge domain's VRF),
``fvRsBd`` (the bridge domain an EPG uses) and ``fvBD`` (to resolve a bridge domain named without a
tenant: the same tenant first, then ``common``, as the APIC does). External EPG subnets
(``l3extSubnet``) are not gateway subnets and are not read. The names follow the documented MIT and
could not be checked on the DevNet sandbox.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
from typing import Any, Protocol

from models.aci_subnets import AciSubnet
from services.aci.common.coerce import text
from services.aci.credentials import AciCredentials

# A read fails with ``too_many_objects`` instead of being truncated.
MAX_SUBNET_ROWS = 100_000
COMMON_TENANT = "common"

_SUBNET_DN = re.compile(r"^uni/tn-([^/]+)/(?:BD-([^/]+)|ap-([^/]+)/epg-([^/]+))/subnet-\[(.+)\]$")
_BD_DN = re.compile(r"^uni/tn-([^/]+)/BD-([^/]+)$")
_BD_CHILD = re.compile(r"^uni/tn-([^/]+)/BD-([^/]+)/")
_EPG_CHILD = re.compile(r"^uni/tn-([^/]+)/ap-([^/]+)/epg-([^/]+)/")
_CLASSES = ("fvBD", "fvRsCtx", "fvRsBd", "fvSubnet")


class AciSubnetClient(Protocol):
    async def query_class(
        self,
        credentials: AciCredentials,
        class_name: str,
        *,
        query_filter: str | None = None,
        max_objects: int = ...,
    ) -> list[dict[str, Any]]: ...


class AciSubnetService:
    """Read-only subnet listing for one APIC source (credentials already resolved)."""

    def __init__(self, client: AciSubnetClient, credentials: AciCredentials) -> None:
        self._client = client
        self._credentials = credentials

    async def list_subnets(self) -> tuple[AciSubnet, ...]:
        fetched = await asyncio.gather(
            *[
                self._client.query_class(self._credentials, name, max_objects=MAX_SUBNET_ROWS)
                for name in _CLASSES
            ]
        )
        rows: dict[str, list[dict[str, Any]]] = dict(zip(_CLASSES, fetched, strict=True))
        bridge_domains = {
            (m.group(1), m.group(2)) for r in rows["fvBD"] if (m := _BD_DN.match(_dn(r)))
        }
        vrf_of_bd = {
            (m.group(1), m.group(2)): name
            for r in rows["fvRsCtx"]
            if (m := _BD_CHILD.match(_dn(r))) and (name := text(r.get("tnFvCtxName")))
        }
        bd_of_epg = {
            (m.group(1), m.group(2), m.group(3)): name
            for r in rows["fvRsBd"]
            if (m := _EPG_CHILD.match(_dn(r))) and (name := text(r.get("tnFvBDName")))
        }

        def resolve_bd(tenant: str, name: str) -> tuple[str, str]:
            if (tenant, name) in bridge_domains:
                return tenant, name
            return (
                (COMMON_TENANT, name) if (COMMON_TENANT, name) in bridge_domains else (tenant, name)
            )

        subnets = []
        for row in rows["fvSubnet"]:
            match = _SUBNET_DN.match(_dn(row))
            parsed = _parse_address(text(row.get("ip")))
            if match is None or parsed is None:
                continue
            tenant, bd_name, app_profile, epg_name, _ = match.groups()
            if bd_name is None:  # an EPG subnet lives in the bridge domain its EPG uses
                bd_name = bd_of_epg.get((tenant, app_profile, epg_name))
            bd_key = resolve_bd(tenant, bd_name) if bd_name else None
            subnets.append(
                AciSubnet(
                    prefix=parsed[0],
                    gateway=parsed[1],
                    tenant=tenant,
                    bridge_domain=bd_key[1] if bd_key else None,
                    vrf=vrf_of_bd.get(bd_key) if bd_key else None,
                    owner="bd" if epg_name is None else "epg",
                    epg=epg_name,
                    scope=_flags(row.get("scope")),
                )
            )
        return tuple(sorted(subnets, key=lambda s: (s.tenant, s.prefix, s.bridge_domain or "")))


def _dn(row: dict[str, Any]) -> str:
    return text(row.get("dn")) or ""


def _parse_address(value: str | None) -> tuple[str, str] | None:
    """``(network, gateway)`` of ``10.1.1.1/24``, or ``None`` for anything else."""
    if not value or "/" not in value:
        return None
    try:
        interface = ipaddress.ip_interface(value)
    except ValueError:
        return None
    return str(interface.network), str(interface.ip)


def _flags(value: Any) -> tuple[str, ...]:
    return tuple(part for item in (text(value) or "").split(",") if (part := item.strip()))
