#!/usr/bin/env python3
"""Which saved workflows (and Jinja templates) need an update after the workflow-step refactor.

Read-only. It reads ``workflows`` and ``templates`` from the database configured in backend/.env
(``DATABASE_*``, like the app) and prints one block per workflow that has a finding. Nothing is
written. The changes it looks for are listed in
``doc/analysis/workflow_steps/IMPORTANT_CHANGES.md``.

Usage (from backend/, with the project venv active):

    python scripts/check_workflow_for_changes.py          # workflows + templates in the DB
    python scripts/check_workflow_for_changes.py --all    # also workflows without findings
    python scripts/check_workflow_for_changes.py --json   # machine-readable output
    # check exported *.json files instead of the database:
    python scripts/check_workflow_for_changes.py --export-dir ../contributing-data/workflow-gallery

Severities:
    BREAKS  the workflow fails or silently does the wrong thing until it is changed
    CHECK   behaviour changed; review the workflow and test-run it once
    INFO    harmless leftover or changed wording; nothing to do unless you rely on it

Exit code: 1 when at least one BREAKS finding exists, else 0.

The registry check (unknown step kinds, unknown config keys, boolean strings that no longer parse)
uses ``workflow_steps/registry.yaml`` through the plugin registry service, the same source the
app uses when it saves a workflow.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import logging  # noqa: E402

logging.basicConfig(level=logging.WARNING)

from services.workflow.config_normalisation import (  # noqa: E402
    default_plugin_lookup,
    normalise_plugin_config,
)

BREAKS = "BREAKS"
CHECK = "CHECK"
INFO = "INFO"
_SEVERITY_ORDER = {BREAKS: 0, CHECK: 1, INFO: 2}

# Steps that now write parsed[<node_id>][<output_key>] instead of parsed[<output_key>] (fd75b46),
# with their get_config() default output_key (kept here: scripts do not import workflow_steps).
FACT_STEP_DEFAULT_KEYS: dict[str, str] = {
    "batfish-extract-facts": "batfish_extract_facts",
    "undefined-and-unused": "undefined_and_unused",
    "get-pyats-running-config": "pyats_config",
    "get-pyats-snapshot": "pyats_snapshot",
}

# run-command still writes the flat parsed[<parsed_output_key>]; its get_config() default.
RUN_COMMAND_DEFAULT_KEY = "parsed"

# content_resolver: these sources need source_step_node_id (pyats_snapshot is new, b3bba81).
SOURCES_NEEDING_NODE = frozenset(
    {
        "command_output",
        "rendered_template",
        "pyats_snapshot",
        "merged_content",
        "comparison_diff",
        "filtered_output",
        "updated_content",
    }
)

# update-attribute's old flat single-update shape (refused since 19c05f9).
UPDATE_ATTRIBUTE_FLAT_KEYS = frozenset(
    {"mode", "destination_path", "fixed_value", "source_path", "pattern", "destination_template"}
)

# Keys the registry no longer declares, with what their presence means now.
REMOVED_KEYS: dict[tuple[str, str], tuple[str, str]] = {
    ("run-command", "use_textfsm"): (
        BREAKS,
        "removed (2026-10-17); set parser: textfsm and parsed_output_key instead",
    ),
    ("run-command", "use_genie"): (
        BREAKS,
        "removed (2026-10-17); set parser: genie and pyats_source_id instead",
    ),
    ("run-command", "genie_output_key"): (
        BREAKS,
        "removed (2026-10-17); the output now goes to parsed_output_key",
    ),
    ("render-jinja-template", "template"): (
        BREAKS,
        "inline templates are refused (19c05f9); store the template and set template_id",
    ),
    ("set-default-attributes", "type"): (INFO, "removed (3b16f7a) and ignored; delete it"),
    ("store-artifact", "retention_policy"): (
        INFO,
        "removed (1f11559); it was reserved and never used; delete it",
    ),
    ("fan-in", "label"): (INFO, "removed (1f11559) and ignored; delete it"),
    ("from-change-request", "checkout_branch"): (
        INFO,
        "removed (1f11559); the branch is checked out only with load_configs",
    ),
}
ANY_STEP_REMOVED_KEYS: dict[str, tuple[str, str]] = {
    "use_change_request_branch": (INFO, "ignored since a2e0fab; delete it"),
}

_UUID_PLACEHOLDER = re.compile(r"[{]")


@dataclass(frozen=True)
class Finding:
    severity: str
    node_id: str
    kind: str
    message: str


@dataclass(frozen=True)
class WorkflowReport:
    source: str
    workflow_id: str
    name: str
    findings: tuple[Finding, ...]
    template_ids: tuple[int, ...] = field(default=())


@dataclass(frozen=True)
class TemplateReport:
    template_id: int
    name: str
    used_by: tuple[str, ...]
    findings: tuple[str, ...]


@dataclass(frozen=True)
class Node:
    node_id: str
    kind: str
    config: dict[str, Any]


# --------------------------------------------------------------------------------------------
# helpers


def _nodes(canvas_nodes: Any) -> list[Node]:
    result: list[Node] = []
    for raw in canvas_nodes or []:
        if not isinstance(raw, dict):
            continue
        data = raw.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("kind"), str):
            continue
        config = data.get("pluginConfig")
        result.append(
            Node(
                node_id=str(raw.get("id", "?")),
                kind=data["kind"],
                config=config if isinstance(config, dict) else {},
            )
        )
    return result


def _strings(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in a config value as (dotted key path, text)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(item, f"{path}.{key}" if path else str(key))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


def _flat_parsed_pattern(output_key: str) -> re.Pattern[str]:
    """``parsed.<key>`` or ``parsed['<key>']``, but not ``parsed.<node_id>.<key>``."""
    return re.compile(r"parsed(?:\.|\[\s*['\"])" + re.escape(output_key) + r"(?![\w-])")


def _is_true(config: dict[str, Any], key: str) -> bool:
    value = config.get(key)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _fact_outputs(nodes: list[Node]) -> dict[str, str]:
    """output_key -> node id of every fact step in the workflow."""
    outputs: dict[str, str] = {}
    for node in nodes:
        default = FACT_STEP_DEFAULT_KEYS.get(node.kind)
        if default is not None:
            key = str(node.config.get("output_key") or default).strip()
            outputs[key] = node.node_id
    return outputs


# --------------------------------------------------------------------------------------------
# workflow rules


def _registry_findings(node: Node) -> list[Finding]:
    plugin = default_plugin_lookup(node.kind)
    if plugin is None:
        return [Finding(BREAKS, node.node_id, node.kind, "step kind is not in the registry")]
    findings: list[Finding] = []
    declared = {item.name for item in plugin.metadata.configuration_input}
    for key in node.config:
        if key in declared:
            continue
        severity, message = REMOVED_KEYS.get(
            (node.kind, key),
            ANY_STEP_REMOVED_KEYS.get(key, (CHECK, "not declared in the registry; it is ignored")),
        )
        findings.append(
            Finding(severity, node.node_id, node.kind, f"config key '{key}': {message}")
        )
    try:
        normalise_plugin_config(plugin, node.config, strict=True)
    except ValueError as exc:
        findings.append(Finding(BREAKS, node.node_id, node.kind, f"boolean value: {exc}"))
    return findings


def _reachable(edges: Any) -> dict[str, set[str]] | None:
    """node id -> every node id downstream of it; ``None`` when the workflow has no edges."""
    if not isinstance(edges, list) or not edges:
        return None
    children: dict[str, set[str]] = {}
    for edge in edges:
        if isinstance(edge, dict) and edge.get("source") and edge.get("target"):
            children.setdefault(str(edge["source"]), set()).add(str(edge["target"]))
    reach: dict[str, set[str]] = {}
    for start in children:
        seen: set[str] = set()
        stack = list(children[start])
        while stack:
            current = stack.pop()
            if current not in seen:
                seen.add(current)
                stack.extend(children.get(current, ()))
        reach[start] = seen
    return reach


def _flat_writers(nodes: list[Node]) -> dict[str, list[str]]:
    """Flat key -> node ids of the steps that still write ``parsed[<key>]`` (run-command)."""
    writers: dict[str, list[str]] = {}
    for node in nodes:
        if node.kind == "run-command":
            key = str(node.config.get("parsed_output_key") or RUN_COMMAND_DEFAULT_KEY).strip()
            writers.setdefault(key, []).append(node.node_id)
    return writers


def _upstream_of(reach: dict[str, set[str]] | None, source: str, target: str) -> bool:
    """``True`` when ``source`` runs before ``target`` (always ``True`` without edges)."""
    return reach is None or target in reach.get(source, set())


def _flat_parsed_findings(
    node: Node,
    outputs: dict[str, str],
    reach: dict[str, set[str]] | None,
    flat_writers: dict[str, list[str]],
) -> list[Finding]:
    findings: list[Finding] = []
    for output_key, fact_node in outputs.items():
        if fact_node == node.node_id or not _upstream_of(reach, fact_node, node.node_id):
            continue
        shared = [
            writer
            for writer in flat_writers.get(output_key, [])
            if writer != node.node_id and _upstream_of(reach, writer, node.node_id)
        ]
        pattern = _flat_parsed_pattern(output_key)
        for path, text in _strings(node.config):
            if not pattern.search(text):
                continue
            message = (
                f"'{path}' reads parsed.{output_key}; {fact_node} now writes "
                f"parsed.{fact_node}.{output_key}"
            )
            severity = BREAKS
            if shared:
                severity = CHECK
                message += (
                    f", but {', '.join(shared)} also writes the flat parsed.{output_key}; "
                    "fine if the path is meant for that step's output"
                )
            findings.append(Finding(severity, node.node_id, node.kind, message))
    return findings


def _config_to_attributes_findings(node: Node, outputs: dict[str, str]) -> list[Finding]:
    fmt = str(node.config.get("source_format") or "").strip().lower()
    parsed_key = str(node.config.get("parsed_key") or "").strip()
    if fmt not in {"batfish", "genie"} or not parsed_key or "." in parsed_key:
        return []
    fact_node = outputs.get(parsed_key, "<node id of the fact step>")
    return [
        Finding(
            BREAKS,
            node.node_id,
            node.kind,
            f"parsed_key '{parsed_key}' is a flat key; the {fmt} format needs "
            f"'{fact_node}.{parsed_key}'",
        )
    ]


def _content_source_findings(node: Node) -> list[Finding]:
    source = str(node.config.get("content_source") or "").strip().lower()
    if source not in SOURCES_NEEDING_NODE:
        return []
    if str(node.config.get("source_step_node_id") or "").strip():
        return []
    if _is_true(node.config, "any_source_step"):
        return []
    return [
        Finding(
            BREAKS,
            node.node_id,
            node.kind,
            f"content_source '{source}' needs source_step_node_id (it is empty)",
        )
    ]


def _matched_text_findings(nodes: list[Node]) -> list[Finding]:
    route_nodes = [n for n in nodes if n.kind == "route-on-content"]
    off = {n.node_id for n in route_nodes if not _is_true(n.config, "store_matched_text")}
    if not off:
        return []
    findings: list[Finding] = []
    for node in nodes:
        for path, text in _strings(node.config):
            if "matched_text" not in text:
                continue
            named = [rid for rid in off if rid in text]
            targets = named or sorted(off)
            findings.append(
                Finding(
                    BREAKS,
                    node.node_id,
                    node.kind,
                    f"'{path}' reads matched_text, but store_matched_text is off on "
                    f"{', '.join(targets)} (fed6753); turn it on there",
                )
            )
    return findings


def _step_specific_findings(node: Node) -> list[Finding]:
    cfg, nid, kind = node.config, node.node_id, node.kind
    found: list[Finding] = []
    if kind == "render-jinja-template" and cfg.get("template_id") in (None, ""):
        found.append(Finding(BREAKS, nid, kind, "no template_id; only stored templates are used"))
    if kind == "update-attribute":
        flat = sorted(UPDATE_ATTRIBUTE_FLAT_KEYS & set(cfg))
        if flat or not isinstance(cfg.get("attributes"), list):
            found.append(
                Finding(
                    BREAKS,
                    nid,
                    kind,
                    "old flat config (" + ", ".join(flat or ["no attributes list"]) + "); "
                    "re-create the update in the attributes list",
                )
            )
    if _is_batfish_query(kind):
        source = str(cfg.get("batfish_source_id") or "").strip()
        network = str(cfg.get("network") or "").strip()
        if bool(source) != bool(network):
            found.append(
                Finding(
                    BREAKS,
                    nid,
                    kind,
                    "only one of batfish_source_id / network is set, now a config error "
                    "(310fad9); clear both to use this run's snapshot, or set both",
                )
            )
    if kind == "batfish-path-check" and _is_true(cfg, "invert_search"):
        found.append(Finding(BREAKS, nid, kind, "invert_search is now a config error"))
    if kind == "check-nautobot-job":
        job_uuid = str(cfg.get("job_uuid") or "").strip()
        if job_uuid and not _UUID_PLACEHOLDER.search(job_uuid) and not _is_uuid(job_uuid):
            found.append(Finding(BREAKS, nid, kind, f"job_uuid '{job_uuid}' is not a UUID"))
    found.extend(_behaviour_findings(node))
    return found


def _is_batfish_query(kind: str) -> bool:
    """Steps whose Batfish target is "source + network, or neither" (parse_direct_target)."""
    if kind == "batfish-init-snapshot":
        return False
    return kind.startswith("batfish-") or kind in {"get-batfish-devices", "undefined-and-unused"}


def _is_uuid(text: str) -> bool:
    try:
        uuid.UUID(text)
    except ValueError:
        return False
    return True


_BEHAVIOUR_NOTES: dict[str, tuple[str, str]] = {
    "batfish-acl-check": (CHECK, "'permit' now needs every matching filter to permit (bb29934)"),
    "contact-the-ai": (CHECK, "a failed AI call now marks the devices FAILED, not OK (6e09254)"),
    "collect-client-data": (INFO, "LLDP neighbours store the port id, not the description"),
    "remove-from-nautobot": (INFO, "dry_run stores a preview in dry_run_results"),
    "update-config-context": (INFO, "dry_run stores a preview in dry_run_results"),
}


def _behaviour_findings(node: Node) -> list[Finding]:
    cfg, nid, kind = node.config, node.node_id, node.kind
    found: list[Finding] = []
    note = _BEHAVIOUR_NOTES.get(kind)
    if note is not None:
        found.append(Finding(note[0], nid, kind, note[1]))
    if kind == "set-default-attributes" and str(cfg.get("mode") or "") == "git":
        found.append(
            Finding(CHECK, nid, kind, "several files matching filename_pattern now fail the step")
        )
    if kind == "batfish-init-snapshot" and str(cfg.get("retain_snapshots", "x")).strip() == "":
        found.append(Finding(CHECK, nid, kind, "blank retain_snapshots now keeps 5, not all"))
    if (
        kind == "from-change-request"
        and _is_true(cfg, "checkout_branch")
        and "load_configs" in cfg
        and not _is_true(cfg, "load_configs")
    ):
        found.append(
            Finding(
                CHECK,
                nid,
                kind,
                "checkout_branch is gone; with load_configs off the manus/cr-{id} branch is no "
                "longer checked out for later git-reading steps (1f11559)",
            )
        )
    if kind == "update-nautobot-device" and _is_true(cfg, "dry_run"):
        found.append(Finding(INFO, nid, kind, "dry_run is a read-only plan now, not a skip"))
    for path, text in _strings(cfg):
        if "error.message" in text:
            found.append(
                Finding(
                    INFO,
                    nid,
                    kind,
                    f"'{path}' uses error.message: the syntax is still valid; the text is "
                    "now the app's own sentence (no driver or SQL text); {error.code} adds "
                    "the reason code",
                )
            )
    return found


def check_workflow(
    source: str, workflow_id: str, name: str, canvas_nodes: Any, canvas_edges: Any = None
) -> WorkflowReport:
    nodes = _nodes(canvas_nodes)
    outputs = _fact_outputs(nodes)
    reach = _reachable(canvas_edges)
    flat_writers = _flat_writers(nodes)
    findings: list[Finding] = []
    for node in nodes:
        findings.extend(_registry_findings(node))
        findings.extend(_flat_parsed_findings(node, outputs, reach, flat_writers))
        if node.kind == "config-to-attributes":
            findings.extend(_config_to_attributes_findings(node, outputs))
        findings.extend(_content_source_findings(node))
        findings.extend(_step_specific_findings(node))
    findings.extend(_matched_text_findings(nodes))
    template_ids = sorted(
        {
            int(n.config["template_id"])
            for n in nodes
            if str(n.config.get("template_id") or "").strip().isdigit()
        }
    )
    ordered = sorted(findings, key=lambda f: (_SEVERITY_ORDER[f.severity], f.node_id))
    return WorkflowReport(source, workflow_id, name, tuple(ordered), tuple(template_ids))


# --------------------------------------------------------------------------------------------
# templates


def check_template(
    template_id: int,
    name: str,
    content: str,
    fact_keys: set[str],
    reports: list[WorkflowReport],
) -> TemplateReport:
    findings: list[str] = []
    for key in sorted(fact_keys):
        if _flat_parsed_pattern(key).search(content or ""):
            findings.append(
                f"BREAKS reads parsed.{key}; fact steps now write parsed['<node_id>'].{key}"
            )
    if "matched_text" in (content or ""):
        findings.append("CHECK reads matched_text; route-on-content needs store_matched_text on")
    used_by = tuple(f"{r.workflow_id} {r.name}" for r in reports if template_id in r.template_ids)
    return TemplateReport(template_id, name, used_by, tuple(findings))


def _all_fact_keys(rows: list[tuple[str, str, str, Any, Any]]) -> set[str]:
    keys = set(FACT_STEP_DEFAULT_KEYS.values())
    for _, _, _, canvas_nodes, _ in rows:
        keys.update(_fact_outputs(_nodes(canvas_nodes)))
    return keys


# --------------------------------------------------------------------------------------------
# input


def _rows_from_exports(directory: Path) -> list[tuple[str, str, str, Any, Any]]:
    rows: list[tuple[str, str, str, Any, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[skip] {path.name}: {exc.__class__.__name__}", file=sys.stderr)
            continue
        if isinstance(data, dict):
            rows.append(
                (
                    "file",
                    path.name,
                    str(data.get("name", path.stem)),
                    data.get("canvas_nodes"),
                    data.get("canvas_edges"),
                )
            )
    return rows


def _rows_from_database() -> tuple[
    list[tuple[str, str, str, Any, Any]], list[tuple[int, str, str]]
]:
    from sqlalchemy import select

    from core.database import SessionLocal
    from core.models import Template, Workflow

    with SessionLocal() as db:
        workflows = db.execute(
            select(
                Workflow.id, Workflow.name, Workflow.canvas_nodes, Workflow.canvas_edges
            ).order_by(Workflow.id)
        ).all()
        templates = db.execute(
            select(Template.id, Template.name, Template.content)
            .where(Template.is_active.is_(True))
            .order_by(Template.id)
        ).all()
    rows = [("db", str(w.id), w.name, w.canvas_nodes, w.canvas_edges) for w in workflows]
    return rows, [(t.id, t.name, t.content or "") for t in templates]


# --------------------------------------------------------------------------------------------
# output


def _print_text(
    reports: list[WorkflowReport], templates: list[TemplateReport], *, show_all: bool
) -> None:
    flagged = [r for r in reports if r.findings]
    for report in reports:
        if not report.findings and not show_all:
            continue
        worst = report.findings[0].severity if report.findings else "OK"
        print(f"\n[{worst}] workflow {report.workflow_id}: {report.name}")
        for f in report.findings:
            print(f"    {f.severity:<6} {f.node_id} ({f.kind}): {f.message}")
    flagged_templates = [t for t in templates if t.findings]
    for tpl in flagged_templates:
        print(f"\n[template] {tpl.template_id}: {tpl.name}")
        for line in tpl.findings:
            print(f"    {line}")
        print("    used by: " + (", ".join(tpl.used_by) or "no checked workflow"))
    counts = {
        s: sum(1 for r in reports for f in r.findings if f.severity == s) for s in _SEVERITY_ORDER
    }
    print(
        f"\nChecked {len(reports)} workflows and {len(templates)} templates: "
        f"{len(flagged)} workflows and {len(flagged_templates)} templates with findings "
        f"(BREAKS {counts[BREAKS]}, CHECK {counts[CHECK]}, INFO {counts[INFO]})."
    )


def _print_json(reports: list[WorkflowReport], templates: list[TemplateReport]) -> None:
    payload = {
        "workflows": [asdict(r) for r in reports],
        "templates": [asdict(t) for t in templates],
    }
    print(json.dumps(payload, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    parser.add_argument("--export-dir", type=Path, help="check exported workflow *.json files")
    parser.add_argument("--all", action="store_true", help="also list workflows without findings")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)

    if args.export_dir is not None:
        if not args.export_dir.is_dir():
            parser.error(f"not a directory: {args.export_dir}")
        rows, template_rows = _rows_from_exports(args.export_dir), []
    else:
        rows, template_rows = _rows_from_database()

    reports = [check_workflow(*row) for row in rows]
    fact_keys = _all_fact_keys(rows)
    templates = [
        check_template(tid, name, content, fact_keys, reports)
        for tid, name, content in template_rows
    ]

    if args.json:
        _print_json(reports, templates)
    else:
        _print_text(reports, templates, show_all=args.all)
    breaks = any(f.severity == BREAKS for r in reports for f in r.findings) or any(
        line.startswith(BREAKS) for t in templates for line in t.findings
    )
    return 1 if breaks else 0


if __name__ == "__main__":
    sys.exit(main())
