"""Pure row shaping for the Batfish tools: fewer columns, condensed answers.

No I/O, no rights, no redaction (those stay in the tools and the choke point). Every function
returns new data and leaves its input alone. The goal is the one stated in
doc/AI_TOOL_CHAIN.md §6.2 and §15.2 item 3: give the model the answer, not the whole table.

Column names follow Batfish's answer tables. They were taken from the question definitions and
the existing steps, **not yet checked against a live coordinator**; a column that is absent is
simply left out, nothing here fails on an unexpected shape.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Literal, get_args

from services.ai_assistant.tools.envelope import drop_columns

ROUTE_COLUMNS = (
    "Node",
    "VRF",
    "Network",
    "Protocol",
    "Next_Hop",
    "Next_Hop_IP",
    "Next_Hop_Interface",
    "Admin_Distance",
    "Metric",
    "Tag",
)
_LEGACY_NEXT_HOP = frozenset({"Next_Hop_IP", "Next_Hop_Interface"})

INTERFACE_COLUMNS = (
    "Active",
    "Admin_Up",
    "Primary_Address",
    "VRF",
    "Access_VLAN",
    "Allowed_VLANs",
    "Switchport_Mode",
    "MTU",
    "Channel_Group",
    "Incoming_Filter_Name",
    "Outgoing_Filter_Name",
)

BGP_COLUMNS = (
    "Node",
    "VRF",
    "Local_AS",
    "Local_IP",
    "Remote_AS",
    "Remote_Node",
    "Remote_IP",
    "Session_Type",
    "Established_Status",
)
_BGP_OK = "ESTABLISHED"

# A path longer than this is shortened in the text; the real hop count is kept.
MAX_PATH_NODES = 40


def _keep(rows: Iterable[Mapping[str, Any]], columns: Iterable[str]) -> list[dict[str, Any]]:
    wanted = tuple(columns)
    return [{c: row[c] for c in wanted if c in row} for row in rows]


def shape_routes(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Routes without the internal columns; the legacy next-hop columns are dropped when the
    structured ``Next_Hop`` is present (same information twice)."""
    kept = _keep(rows, ROUTE_COLUMNS)
    if any("Next_Hop" in row for row in kept):
        return drop_columns(kept, _LEGACY_NEXT_HOP)
    return kept


def _flatten_interface(cell: Any) -> dict[str, Any]:
    if isinstance(cell, Mapping):
        out: dict[str, Any] = {}
        hostname = cell.get("hostname")
        name = cell.get("interface")
        if hostname is not None:
            out["Node"] = hostname
        if name is not None:
            out["Interface"] = name
        return out
    return {"Interface": cell} if cell is not None else {}


def shape_interfaces(
    rows: Iterable[Mapping[str, Any]], *, include_description: bool = False
) -> list[dict[str, Any]]:
    """One flat record per interface: ``Node`` and ``Interface`` first, then the useful columns.

    ``Description`` is free text typed into the device config, so it can hold anything (a
    password, an instruction). It is left out unless the caller was allowed to include it.
    """
    columns = (*INTERFACE_COLUMNS, "Description") if include_description else INTERFACE_COLUMNS
    shaped = []
    for row in rows:
        record = _flatten_interface(row.get("Interface"))
        record.update({c: row[c] for c in columns if c in row})
        shaped.append(record)
    return shaped


def summarize_bgp_sessions(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Number of sessions per ``Established_Status``."""
    return dict(Counter(str(row.get("Established_Status")) for row in rows))


def shape_bgp_sessions(
    rows: Iterable[Mapping[str, Any]], *, only_problems: bool
) -> list[dict[str, Any]]:
    selected = (
        [row for row in rows if row.get("Established_Status") != _BGP_OK]
        if only_problems
        else list(rows)
    )
    return _keep(selected, BGP_COLUMNS)


# -- traceroute --------------------------------------------------------------------------------


def _ci(mapping: Any, name: str) -> Any:
    """Case-insensitive key lookup: the serialised Trace/Hop objects are not verified live."""
    if not isinstance(mapping, Mapping):
        return None
    for key, value in mapping.items():
        if isinstance(key, str) and key.lower() == name:
            return value
    return None


def _trace_summary(trace: Any) -> tuple[str, tuple[str, ...], str | None] | None:
    disposition = _ci(trace, "disposition")
    hops = _ci(trace, "hops")
    if not isinstance(disposition, str) or not isinstance(hops, list):
        return None
    nodes = tuple(str(_ci(hop, "node")) for hop in hops if _ci(hop, "node") is not None)
    last_action: str | None = None
    if hops:
        steps = _ci(hops[-1], "steps")
        if isinstance(steps, list) and steps:
            action = _ci(steps[-1], "action")
            last_action = str(action) if action is not None else None
    return disposition, nodes, last_action


def _example_flow(flow: Any) -> Any:
    if not isinstance(flow, Mapping):
        return flow
    wanted = ("srcIp", "dstIp", "ipProtocol", "srcPort", "dstPort")
    return {k: flow[k] for k in wanted if k in flow}


def summarize_traces(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Collapse flows with the same (disposition, node path) into one row with a count.

    Returns ``(rows, recognised)``. If any trace has a shape this function does not understand,
    the original rows come back unchanged with ``recognised=False`` so the caller can say so
    instead of presenting a guess.
    """
    groups: dict[tuple[str, tuple[str, ...], str | None], dict[str, Any]] = {}
    for row in rows:
        traces = _ci(row, "traces")
        if not isinstance(traces, list):
            return rows, False
        for trace in traces:
            summary = _trace_summary(trace)
            if summary is None:
                return rows, False
            entry = groups.setdefault(
                summary, {"flows": 0, "example_flow": _example_flow(_ci(row, "flow"))}
            )
            entry["flows"] += 1
    shaped = []
    for (disposition, nodes, last_action), entry in groups.items():
        shown = nodes if len(nodes) <= MAX_PATH_NODES else nodes[:MAX_PATH_NODES]
        shaped.append(
            {
                "disposition": disposition,
                "path": " -> ".join(shown) + (" -> ..." if len(shown) < len(nodes) else ""),
                "hops": len(nodes),
                "last_hop": nodes[-1] if nodes else None,
                "last_action": last_action,
                **entry,
            }
        )
    return shaped, True


# -- device facts ------------------------------------------------------------------------------

# The facts Batfish's extract_facts reports that are safe and small enough to offer to the model:
# names, addresses and settings. Left out on purpose: key material (``IKE_Phase1_Keys``,
# ``Authentication_Key_Chains``, ``IPsec_*``) and the large structures that have their own tools or
# would flood the prompt (``Interfaces``, the access lists, routing policies, route filters).
FactKey = Literal[
    "Hostname",
    "Domain_Name",
    "Configuration_Format",
    "DNS_Servers",
    "DNS_Source_Interface",
    "Logging_Servers",
    "Logging_Source_Interface",
    "NTP_Servers",
    "NTP_Source_Interface",
    "SNMP_Trap_Servers",
    "SNMP_Source_Interface",
    "TACACS_Servers",
    "TACACS_Source_Interface",
    "VRFs",
    "Zones",
]
FACT_KEYS: tuple[str, ...] = get_args(FactKey)
DEFAULT_FACT_KEYS: tuple[FactKey, ...] = (
    "Hostname",
    "Logging_Servers",
    "NTP_Servers",
    "DNS_Servers",
    "TACACS_Servers",
    "SNMP_Trap_Servers",
)


# Batfish groups these facts under a section name (pybatfish ``NODE_PROPERTIES_REORG``): a node's
# syslog servers are ``Facts["Syslog"]["Logging_Servers"]``, not ``Facts["Logging_Servers"]``.
# Plain facts (Hostname, Domain_Name, VRFs, ...) stay top-level. ``IPsec`` is deliberately absent:
# it holds key material and is never offered.
_FACT_SECTIONS = ("DNS", "NTP", "Syslog", "SNMP", "TACACS")


def _node_facts(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """A node's facts with the section names folded away, so the model asks for
    ``Logging_Servers`` and not for where Batfish happens to file it."""
    facts = row.get("Facts")
    if not isinstance(facts, Mapping):
        return {}
    flat: dict[str, Any] = {k: v for k, v in facts.items() if k not in _FACT_SECTIONS}
    for section in _FACT_SECTIONS:
        inner = facts.get(section)
        if isinstance(inner, Mapping):
            flat.update({k: v for k, v in inner.items() if k not in flat})
        elif section in facts:
            flat.setdefault(section, facts[section])  # not the expected shape: keep it visible
    return flat


def _has_value(value: Any) -> bool:
    return value not in (None, "", [], {}, ())


def shape_facts(rows: Iterable[Mapping[str, Any]], keys: Iterable[str]) -> list[dict[str, Any]]:
    """One record per node with only the requested facts that the node reports. A fact the node
    does not report is left out, an empty value stays (``[]`` means 'configured with none')."""
    wanted = tuple(keys)
    shaped = []
    for row in rows:
        facts = _node_facts(row)
        record: dict[str, Any] = {"Node": row.get("Node")}
        record.update({k: facts[k] for k in wanted if k in facts})
        shaped.append(record)
    return shaped


def summarize_facts(
    rows: Iterable[Mapping[str, Any]], keys: Iterable[str]
) -> dict[str, dict[str, int]]:
    """Per requested fact: on how many nodes it has a non-empty value, out of all nodes asked."""
    node_rows = list(rows)
    return {
        key: {
            "nodes_with_values": sum(1 for r in node_rows if _has_value(_node_facts(r).get(key))),
            "nodes_total": len(node_rows),
        }
        for key in keys
    }


def fact_keys_seen(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Names (never values) of the facts Batfish returned, to diagnose a requested key that no
    node reported."""
    return sorted({str(k) for row in rows for k in _node_facts(row)})
