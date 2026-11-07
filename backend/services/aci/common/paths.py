"""Parsing of APIC path target DNs (``topology/pod-1/paths-101/pathep-[eth1/5]``)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# ``paths-<node>`` is one switch, ``protpaths-<a>-<b>`` a vPC across two.
_PATH_TDN = re.compile(
    r"^topology/pod-(\d+)/(?:paths-(\d+)|protpaths-(\d+)-(\d+))/pathep-\[(.+)\]$"
)


@dataclass(frozen=True)
class AciPath:
    pod_id: int
    node_ids: tuple[int, ...]
    interface: str


def parse_path(target_dn: str | None) -> AciPath | None:
    """The pod, node(s) and interface a path DN names, or ``None`` for any other shape."""
    match = _PATH_TDN.match(target_dn or "")
    if match is None:
        return None
    pod, single, first, second, interface = match.groups()
    nodes = (int(single),) if single else (int(first), int(second))
    return AciPath(pod_id=int(pod), node_ids=nodes, interface=interface)
