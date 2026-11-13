"""Turn a crawl into the devices and the summary a workflow step hands on (pure)."""

from __future__ import annotations

import hashlib
from typing import Any

from models.workflow_context import Capability, DeviceContext, DeviceStatus
from services.workflow_context.node_result import set_node_result
from workflow_steps.discover_network.crawler import CrawlResult, Seen, Visited
from workflow_steps.discover_network.parsing import Neighbor

RESULT_KEY = "discovery"
SOURCE = "discover-network"
# The summary is persisted with the step result: keep it bounded and say so when it was cut.
MAX_SEEN = 500
MAX_EDGES = 1000
MAX_NEIGHBORS_PER_DEVICE = 200


def _neighbor_dict(neighbor: Neighbor) -> dict[str, Any]:
    return {
        "name": neighbor.name,
        "ip": neighbor.ip,
        "reported_ip": neighbor.reported_ip,
        "ip_source": neighbor.ip_source,
        "platform": neighbor.platform,
        "local_port": neighbor.local_port,
        "remote_port": neighbor.remote_port,
        "capabilities": list(neighbor.capabilities),
    }


def device_summary(visited: Visited) -> dict[str, Any]:
    """The per-device record under ``parsed.<node id>.discovery``."""
    neighbors = visited.neighbors[:MAX_NEIGHBORS_PER_DEVICE]
    return {
        "depth": visited.target.depth,
        "discovered_from": visited.target.discovered_from,
        "cdp_status": visited.status,
        "neighbor_count": len(visited.neighbors),
        "neighbors": [_neighbor_dict(n) for n in neighbors],
    }


def with_discovery(device: DeviceContext, node_id: str, summary: dict[str, Any]) -> DeviceContext:
    return device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "parsed": set_node_result(device.parsed, node_id, RESULT_KEY, summary),
            "capabilities": device.capabilities | {Capability.PARSED},
        }
    )


def discovered_device(visited: Visited, node_id: str) -> DeviceContext:
    """A device that was found through CDP and logged into: identity only, plus its record."""
    target = visited.target
    digest = hashlib.sha256(f"{node_id}:{target.host}".encode()).hexdigest()[:32]
    device = DeviceContext(
        id=f"{SOURCE}-{digest}",
        name=target.name,
        hostname=target.host,
        primary_ip4=target.host,
        network_driver=target.device_type,
        source=SOURCE,
        source_id=node_id,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )
    return with_discovery(device, node_id, device_summary(visited))


def _seen_dict(seen: Seen) -> dict[str, Any]:
    return {
        "name": seen.name,
        "ip": seen.ip,
        "reported_ip": seen.reported_ip,
        "ip_source": seen.ip_source,
        "platform": seen.platform,
        "reason": seen.reason,
        "seen_from": seen.seen_from,
        "depth": seen.depth,
    }


def step_summary(
    result: CrawlResult, *, seed_hosts: frozenset[str], management_ip_lookup: str = "off"
) -> dict[str, Any]:
    """The step-level record in ``metadata["<node id>.discovery"]``.

    ``management_ip_lookup`` says what happened to the Nautobot lookup: ``on``, ``off``,
    ``no_source`` (switched on, no Nautobot source chosen) or ``unavailable`` (Nautobot failed).
    """
    seen = result.seen[:MAX_SEEN]
    edges = result.edges[:MAX_EDGES]
    return {
        "management_ip_lookup": management_ip_lookup,
        "visited": [
            {
                "name": v.target.name,
                "ip": v.target.host,
                "depth": v.target.depth,
                "discovered_from": v.target.discovered_from,
                "seed": v.target.host in seed_hosts,
                "cdp_status": v.status,
            }
            for v in result.visited
        ],
        "seen_not_visited": [_seen_dict(s) for s in seen],
        "edges": [
            {
                "from": e.from_name,
                "local_port": e.local_port,
                "to": e.to_name,
                "remote_port": e.remote_port,
                "to_ip": e.to_ip,
                "reported_ip": e.reported_ip,
                "ip_source": e.ip_source,
            }
            for e in edges
        ],
        "limits_hit": list(result.limits_hit),
        "truncated": len(result.seen) > MAX_SEEN or len(result.edges) > MAX_EDGES,
    }
