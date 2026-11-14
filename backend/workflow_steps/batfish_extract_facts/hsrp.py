"""HSRP groups for the extracted facts.

``extract_facts`` (interfaceProperties) lists only the HSRP group ids of an interface
(``HSRP_Groups: ["0"]``); the virtual IP, priority and preempt flag are in Batfish's separate
``hsrpProperties`` question. This merges its rows into the facts as
``Interfaces.<name>.HSRP_Details`` so ``config-to-attributes`` can build redundancy groups.
Batfish does not parse ``standby <n> name`` (it is a parse warning), so there is no group name.
"""

from __future__ import annotations

from typing import Any


def _row_target(row: Any) -> tuple[str, str] | None:
    """(node, interface) lower-cased from a row's ``Interface`` identity, else None."""
    identity = row.get("Interface") if isinstance(row, dict) else None
    if not isinstance(identity, dict):
        return None
    node, interface = identity.get("hostname"), identity.get("interface")
    if not isinstance(node, str) or not isinstance(interface, str):
        return None
    return node.strip().lower(), interface.strip().lower()


def _details(row: dict[str, Any]) -> dict[str, Any] | None:
    group_id = row.get("Group_Id")
    if group_id is None or isinstance(group_id, bool):
        return None
    addresses = row.get("Virtual_Addresses")
    return {
        "Group_Id": str(group_id),
        "Virtual_Addresses": [str(a) for a in addresses] if isinstance(addresses, list) else [],
        "Priority": row.get("Priority"),
        "Preempt": row.get("Preempt"),
        "Active": row.get("Active"),
    }


def _group_sort_key(details: dict[str, Any]) -> tuple[int, str]:
    group_id = details["Group_Id"]
    return (int(group_id), group_id) if group_id.isdigit() else (1 << 30, group_id)


def merge_hsrp_into_facts(facts: dict[str, Any], rows: list[Any]) -> dict[str, Any]:
    """A copy of ``facts`` whose interfaces carry ``HSRP_Details`` (groups of ``rows``).

    A row for an unknown node or interface, or a malformed row, is ignored.
    """
    nodes = facts.get("nodes") if isinstance(facts, dict) else None
    if not isinstance(nodes, dict):
        return facts

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        target = _row_target(row)
        details = _details(row) if target else None
        if target and details:
            grouped.setdefault(target, []).append(details)
    if not grouped:
        return facts

    new_nodes: dict[str, Any] = {}
    for node_name, node in nodes.items():
        interfaces = node.get("Interfaces") if isinstance(node, dict) else None
        if not isinstance(interfaces, dict):
            new_nodes[node_name] = node
            continue
        new_interfaces = {}
        for iface_name, iface in interfaces.items():
            groups = grouped.get((str(node_name).lower(), str(iface_name).lower()))
            if groups and isinstance(iface, dict):
                iface = {**iface, "HSRP_Details": sorted(groups, key=_group_sort_key)}
            new_interfaces[iface_name] = iface
        new_nodes[node_name] = {**node, "Interfaces": new_interfaces}
    return {**facts, "nodes": new_nodes}


def mark_hsrp_error(facts: dict[str, Any], message: str) -> dict[str, Any]:
    """A copy of ``facts`` whose nodes with HSRP groups carry ``HSRP_Details_Error``.

    Used when ``hsrpProperties`` failed: the interface facts still list the group ids, so without
    this a device with HSRP would look like one whose groups were simply not found. A node
    without any HSRP group is left alone.
    """
    nodes = facts.get("nodes") if isinstance(facts, dict) else None
    if not isinstance(nodes, dict):
        return facts
    marked: dict[str, Any] = {}
    for node_name, node in nodes.items():
        interfaces = node.get("Interfaces") if isinstance(node, dict) else None
        has_groups = isinstance(interfaces, dict) and any(
            isinstance(iface, dict) and iface.get("HSRP_Groups") for iface in interfaces.values()
        )
        marked[node_name] = {**node, "HSRP_Details_Error": message} if has_groups else node
    return {**facts, "nodes": marked}
