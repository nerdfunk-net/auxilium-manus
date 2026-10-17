"""Network topology from Cisco Catalyst Center (read-only).

``GET /topology/network-topology`` does not exist (404 on the DevNet sandbox). The graphs
that do, and that were verified live there: ``/topology/physical-topology`` and
``/topology/l3/{ospf,isis,eigrp,static}`` (``bgp`` is rejected with HTTP 400). Each returns a
controller-wide ``{"nodes": [...], "links": [...]}`` graph.
"""

from __future__ import annotations

from typing import Any

from models.catalyst_center_facts import (
    CatalystCenterTopology,
    CatalystCenterTopologyLink,
    CatalystCenterTopologyNode,
)
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.coerce import text
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials

_TOPOLOGY = "/dna/intent/api/v1/topology"
PHYSICAL_TOPOLOGY_PATH = f"{_TOPOLOGY}/physical-topology"
L3_TOPOLOGY_PATH = f"{_TOPOLOGY}/l3"
L3_PROTOCOLS = frozenset({"ospf", "isis", "eigrp", "static"})


class CatalystCenterTopologyService:
    def __init__(
        self, client: CatalystCenterService, credentials: CatalystCenterCredentials
    ) -> None:
        self._client = client
        self._credentials = credentials

    async def get_physical_topology(self) -> CatalystCenterTopology:
        return await self._fetch(PHYSICAL_TOPOLOGY_PATH)

    async def get_l3_topology(self, protocol: str) -> CatalystCenterTopology:
        if protocol not in L3_PROTOCOLS:
            raise CatalystCenterValidationError(
                f"Unsupported L3 topology protocol; use one of {sorted(L3_PROTOCOLS)}"
            )
        return await self._fetch(f"{L3_TOPOLOGY_PATH}/{protocol}")

    async def _fetch(self, path: str) -> CatalystCenterTopology:
        payload: Any = await self._client.request(self._credentials, "GET", path)
        body = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(body, dict):
            raise CatalystCenterAPIError("Catalyst Center returned an unexpected topology response")
        nodes = body.get("nodes")
        links = body.get("links")
        return CatalystCenterTopology(
            nodes=tuple(
                CatalystCenterTopologyNode(
                    id=node_id,
                    label=text(node.get("label")),
                    ip=text(node.get("ip")),
                    role=text(node.get("role")),
                    family=text(node.get("family")),
                    platform_id=text(node.get("platformId")),
                    software_version=text(node.get("softwareVersion")),
                    device_type=text(node.get("deviceType")),
                    node_type=text(node.get("nodeType")),
                )
                for node in (nodes if isinstance(nodes, list) else [])
                if isinstance(node, dict) and (node_id := text(node.get("id")))
            ),
            links=tuple(
                CatalystCenterTopologyLink(
                    id=text(link.get("id")),
                    source=source,
                    target=target,
                    start_port_name=text(link.get("startPortName")),
                    end_port_name=text(link.get("endPortName")),
                    start_port_speed=text(link.get("startPortSpeed")),
                    end_port_speed=text(link.get("endPortSpeed")),
                    status=text(link.get("linkStatus")),
                )
                for link in (links if isinstance(links, list) else [])
                if isinstance(link, dict)
                and (source := text(link.get("source")))
                and (target := text(link.get("target")))
            ),
        )
