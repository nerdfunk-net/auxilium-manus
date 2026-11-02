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


InterfaceStatus = Literal["all", "active", "inactive", "admin_down", "inactive_but_admin_up"]


def _is(row: Mapping[str, Any], column: str, value: bool) -> bool:
    return row.get(column) is value


_STATUS_TESTS: dict[str, Any] = {
    "all": lambda row: True,
    "active": lambda row: _is(row, "Active", True),
    "inactive": lambda row: _is(row, "Active", False),
    "admin_down": lambda row: _is(row, "Admin_Up", False),
    # Configured up, yet Batfish treats it as inactive: a missing parent interface, port-channel
    # member or other dependency (the "no dependencies" case), not a shutdown.
    "inactive_but_admin_up": lambda row: _is(row, "Active", False) and _is(row, "Admin_Up", True),
}


def filter_interfaces(
    rows: Iterable[Mapping[str, Any]], status: InterfaceStatus
) -> list[Mapping[str, Any]]:
    """The ``interfaceProperties`` rows in one state. A row without the column never matches a
    state that needs it."""
    wanted = _STATUS_TESTS[status]
    return [row for row in rows if wanted(row)]


def summarize_interfaces(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts over *every* interface, so a device with hundreds of them can be described without
    reading them all: totals, how many are active / inactive / shut down, how many Batfish
    deactivated although they are configured up, and the switchport modes."""
    listed = list(rows)
    return {
        "total": len(listed),
        "active": len(filter_interfaces(listed, "active")),
        "inactive": len(filter_interfaces(listed, "inactive")),
        "admin_down": len(filter_interfaces(listed, "admin_down")),
        "inactive_but_admin_up": len(filter_interfaces(listed, "inactive_but_admin_up")),
        # Rows the answer gave no yes/no for: they are in ``total`` but in neither bucket above.
        "active_unknown": sum(1 for row in listed if not isinstance(row.get("Active"), bool)),
        "admin_up_unknown": sum(1 for row in listed if not isinstance(row.get("Admin_Up"), bool)),
        "by_switchport_mode": dict(
            Counter(str(row["Switchport_Mode"]) for row in listed if row.get("Switchport_Mode"))
        ),
    }


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


def _path_text(nodes: tuple[str, ...]) -> str:
    shown = nodes if len(nodes) <= MAX_PATH_NODES else nodes[:MAX_PATH_NODES]
    return " -> ".join(shown) + (" -> ..." if len(shown) < len(nodes) else "")


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
        shaped.append(
            {
                "disposition": disposition,
                "path": _path_text(nodes),
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


# -- filter (ACL) results ----------------------------------------------------------------------

FILTER_COLUMNS = ("Node", "Filter_Name", "Action")


def shape_filter_results(
    rows: Iterable[Mapping[str, Any]], *, include_line: bool
) -> list[dict[str, Any]]:
    """The verdict of ``testFilters`` per (node, filter): action, and with ``include_line`` the
    matching config line (``Line_Content``, config text, so it needs the content opt-in). The
    internal ``Trace`` column is never passed on; the tested flow is kept in short form."""
    columns = (*FILTER_COLUMNS, "Line_Content") if include_line else FILTER_COLUMNS
    shaped = []
    for row in rows:
        record = {c: row[c] for c in columns if c in row}
        if "Flow" in row:
            record["Flow"] = _example_flow(row["Flow"])
        shaped.append(record)
    return shaped


# -- differential (two snapshots) --------------------------------------------------------------

COMPARISON_COLUMNS = (
    "Node",
    "Filter_Name",
    "Line_Index",
    "Line_Action",
    "Reference_Line_Index",
)
# compareFilters only returns lines whose actions differ, so the reference action is the opposite.
_OPPOSITE_ACTION = {"PERMIT": "DENY", "DENY": "PERMIT"}
COMPARISON_LINE_COLUMNS = ("Line_Content", "Reference_Line_Content")


def shape_filter_comparison(
    rows: Iterable[Mapping[str, Any]], *, include_lines: bool
) -> list[dict[str, Any]]:
    """``compareFilters`` rows: where the same-named filter treats a flow differently in the two
    snapshots. Batfish returns no reference action column; since only lines with different actions
    are listed, ``Reference_Line_Action`` is derived as the opposite of ``Line_Action``. The line
    text is config content, so it needs ``include_lines`` (the content opt-in)."""
    columns = (
        (*COMPARISON_COLUMNS, *COMPARISON_LINE_COLUMNS) if include_lines else COMPARISON_COLUMNS
    )
    shaped = _keep(rows, columns)
    for record in shaped:
        opposite = _OPPOSITE_ACTION.get(str(record.get("Line_Action", "")).upper())
        if opposite is not None:
            record["Reference_Line_Action"] = opposite
    return shaped


def _side(traces: Any) -> list[dict[str, Any]] | None:
    """One side of a differential row as ``[{disposition, path, traces}]``, grouped; ``None`` when
    the shape is not understood."""
    if not isinstance(traces, list):
        return None
    groups: Counter[tuple[str, str]] = Counter()
    for trace in traces:
        summary = _trace_summary(trace)
        if summary is None:
            return None
        disposition, nodes, _ = summary
        groups[(disposition, _path_text(nodes))] += 1
    return [
        {"disposition": disposition, "path": path, "traces": count}
        for (disposition, path), count in groups.items()
    ]


def summarize_differential_traces(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    """``differentialReachability`` rows (``Flow``, ``Snapshot_Traces``, ``Reference_Traces``)
    condensed to one record per flow with the dispositions and paths of both sides.

    Returns ``(rows, recognised)`` like ``summarize_traces``: an unrecognised shape comes back
    unchanged with ``recognised=False`` so the caller says so instead of presenting a guess."""
    shaped = []
    for row in rows:
        in_snapshot = _side(_ci(row, "snapshot_traces"))
        in_reference = _side(_ci(row, "reference_traces"))
        if in_snapshot is None or in_reference is None:
            return rows, False
        shaped.append(
            {
                "flow": _example_flow(_ci(row, "flow")),
                "in_snapshot": in_snapshot,
                "in_reference": in_reference,
            }
        )
    return shaped, True


# -- parse diagnostics -------------------------------------------------------------------------

ParseSection = Literal["all", "files", "warnings", "issues"]
MAX_LINES_PER_GROUP = 10
_PARSE_OK = "PASSED"


def _lines_of(value: Any) -> list[int]:
    return sorted(n for n in value if isinstance(n, int)) if isinstance(value, list) else []


def _file_row(row: Mapping[str, Any]) -> dict[str, Any]:
    shaped = {
        "Section": "file",
        "File_Name": row.get("File_Name"),
        "Nodes": row.get("Nodes") or [],
        "Status": row.get("Status"),
        "Format": row.get("File_Format"),
    }
    return {k: v for k, v in shaped.items() if v is not None}


def _warning_rows(
    warnings: Iterable[Mapping[str, Any]],
    nodes_by_file: Mapping[Any, Any],
    *,
    include_text: bool,
) -> list[dict[str, Any]]:
    """One row per (file, message): parseWarning repeats the same complaint once per line."""
    groups: dict[tuple[Any, Any], list[Mapping[str, Any]]] = {}
    for warning in warnings:
        groups.setdefault((warning.get("Filename"), warning.get("Comment")), []).append(warning)
    shaped = []
    for (filename, message), members in groups.items():
        lines = sorted({n for r in members if isinstance(n := r.get("Line"), int)})
        row: dict[str, Any] = {
            "Section": "warning",
            "File_Name": filename,
            "Nodes": nodes_by_file.get(filename) or [],
            "Message": message,
            "Line": lines[:MAX_LINES_PER_GROUP],
            "Count": len(members),
        }
        if include_text and members[0].get("Text") is not None:
            row["Text"] = members[0]["Text"]
        shaped.append({k: v for k, v in row.items() if v is not None})
    return shaped


def _issue_rows(
    issues: Iterable[Mapping[str, Any]],
    nodes_by_file: Mapping[Any, Any],
    *,
    include_text: bool,
) -> list[dict[str, Any]]:
    shaped = []
    for issue in issues:
        source = issue.get("Source_Lines")
        filename = source.get("filename") if isinstance(source, Mapping) else None
        row: dict[str, Any] = {
            "Section": "issue",
            "File_Name": filename,
            "Nodes": nodes_by_file.get(filename) or [],
            "Status": issue.get("Type"),
            "Line": _lines_of(source.get("lines") if isinstance(source, Mapping) else None)[
                :MAX_LINES_PER_GROUP
            ],
        }
        # ``Details`` can quote names from the config, so it follows the content opt-in.
        if include_text and issue.get("Details") is not None:
            row["Message"] = issue["Details"]
        shaped.append({k: v for k, v in row.items() if v is not None})
    return shaped


def shape_parse_issues(
    *,
    file_status: Iterable[Mapping[str, Any]],
    warnings: Iterable[Mapping[str, Any]],
    issues: Iterable[Mapping[str, Any]],
    section: ParseSection,
    include_passed: bool,
    include_text: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Problem rows of a snapshot's parse diagnostics plus a summary that covers all three answers
    (so ``section`` narrows the rows, never the counts). The summary counts the rows it is given:
    when an answer was cut at the preview cap the caller must say the counts are lower bounds.

    Files that parsed fine are left out unless ``include_passed``; repeated warnings collapse to
    one row with a count; config text (warning lines, issue details) only with ``include_text``.
    """
    files, warns, found = list(file_status), list(warnings), list(issues)
    nodes_by_file = {r.get("File_Name"): r.get("Nodes") for r in files}
    statuses = Counter(str(r.get("Status")) for r in files)
    summary = {
        "files_total": len(files),
        "files_by_status": dict(statuses),
        "warnings_total": len(warns),
        "issues_total": len(found),
    }
    rows: list[dict[str, Any]] = []
    if section in ("all", "files"):
        rows += [_file_row(r) for r in files if include_passed or r.get("Status") != _PARSE_OK]
    if section in ("all", "warnings"):
        rows += _warning_rows(warns, nodes_by_file, include_text=include_text)
    if section in ("all", "issues"):
        rows += _issue_rows(found, nodes_by_file, include_text=include_text)
    return rows, summary
