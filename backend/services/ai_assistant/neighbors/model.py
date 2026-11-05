"""Batfish ``edges`` rows -> neighbour records (doc/AI_TOOL_CHAIN.md §24.14). Pure.

The model knows the L3 and routing-protocol edges the configurations imply. It has no CDP/LLDP
data, so it says nothing about L2 unless a Layer 1 topology was supplied. The endpoint columns
(``Interface``, ``Remote_Interface``) come as ``node[interface]`` text or as a small mapping,
depending on how the answer was flattened; both are read.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from services.ai_assistant.neighbors.records import clean_text

_ENDPOINT = re.compile(r"^(?P<node>[^\[\]]+)\[(?P<interface>[^\[\]]+)\]$")
MAX_IPS = 4


def parse_endpoint(value: Any) -> tuple[str, str]:
    """``(node, interface)`` of an edge endpoint, or empty strings when it cannot be read."""
    if isinstance(value, Mapping):
        node = value.get("hostname") or value.get("node") or ""
        interface = value.get("interface") or ""
        return clean_text(node), clean_text(interface)
    if isinstance(value, str):
        found = _ENDPOINT.match(value.strip())
        if found:
            return clean_text(found.group("node")), clean_text(found.group("interface"))
    return "", ""


def _ips(value: Any) -> list[str]:
    items = value if isinstance(value, (list, tuple)) else [value]
    return [t for t in (clean_text(i, 64) for i in items) if t][:MAX_IPS]


def edge_records(
    rows: Sequence[Mapping[str, Any]], edge_type: str, device: str
) -> list[dict[str, Any]]:
    """The edges that start on ``device`` (case-insensitive), as neighbour records."""
    records: list[dict[str, Any]] = []
    for row in rows:
        node, interface = parse_endpoint(row.get("Interface"))
        remote, remote_interface = parse_endpoint(row.get("Remote_Interface"))
        if not node or not remote or node.lower() != device.lower():
            continue
        records.append(
            {
                "layer": "l3",
                "protocol": edge_type,
                "source": "model",
                "interface": interface,
                "ips": _ips(row.get("IPs")),
                "neighbor_name": remote,
                "neighbor_interface": remote_interface,
                "neighbor_ips": _ips(row.get("Remote_IPs")),
            }
        )
    return records
