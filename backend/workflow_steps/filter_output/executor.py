"""Executor for the filter-output step.

Reads command output or merged content from an upstream step, applies user-configured
filter rules to remove volatile or irrelevant fields, and stores the cleaned result in
device.parsed so downstream compare-data and store-artifact steps can consume it.

Filter rules:
  - pattern: regex matched against JSON key names (recursive) or text lines.
  - path: dot-notation path ("route.ospf") to a specific JSON key to remove.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.content_resolver import ExportableContent, list_exportable_content
from workflow_steps.common.content_step import StoredContent, run_content_step
from workflow_steps.common.regex_search import match_any
from workflow_steps.common.run_logging import log_run_id

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "filter-output"
_SUPPORTED_SOURCES = frozenset({"command_output", "merged_content"})


@dataclass(frozen=True)
class _ParsedFilterConfig:
    content_source: str
    source_step_node_id: str
    source_command: str
    rules: list[dict[str, str]]


def _parse_filter_rules(config: dict[str, Any]) -> list[dict[str, str]]:
    raw = config.get("filter_rules")
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("filter-output: filter_rules must be a list")
    rules: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"filter-output: filter_rules[{i}] must be a dict")
        has_pattern = "pattern" in item and str(item.get("pattern", "")).strip()
        has_path = "path" in item and str(item.get("path", "")).strip()
        if not has_pattern and not has_path:
            raise ValueError(f"filter-output: filter_rules[{i}] must have 'pattern' or 'path'")
        if has_pattern:
            pattern = str(item["pattern"]).strip()
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"filter-output: filter_rules[{i}].pattern {pattern!r} "
                    f"is not valid regex: {exc}"
                ) from exc
            rules.append({"type": "pattern", "value": pattern})
        else:
            rules.append({"type": "path", "value": str(item["path"]).strip()})
    return rules


def _parse_filter_config(config: dict[str, Any]) -> _ParsedFilterConfig:
    content_source = str(config.get("content_source") or "command_output").strip().lower()
    source_step_node_id = str(config.get("source_step_node_id") or "").strip()
    source_command = str(config.get("source_command") or "").strip()

    if content_source not in _SUPPORTED_SOURCES:
        raise ValueError(
            f"filter-output: content_source {content_source!r} must be one of "
            f"{sorted(_SUPPORTED_SOURCES)}"
        )
    if not source_step_node_id:
        raise ValueError("filter-output: source_step_node_id is required")

    rules = _parse_filter_rules(config)
    if not rules:
        raise ValueError("filter-output: at least one rule in filter_rules is required")

    return _ParsedFilterConfig(
        content_source=content_source,
        source_step_node_id=source_step_node_id,
        source_command=source_command,
        rules=rules,
    )


def _key_names(data: Any) -> set[str]:
    """Every object key name in ``data``, at any depth."""
    if isinstance(data, list):
        return {name for item in data for name in _key_names(item)}
    if isinstance(data, dict):
        return set(data) | {name for value in data.values() for name in _key_names(value)}
    return set()


def _apply_pattern_rules(data: Any, dropped: frozenset[str]) -> Any:
    """Recursively remove the object keys whose names are in ``dropped``."""
    if isinstance(data, list):
        return [_apply_pattern_rules(item, dropped) for item in data]
    if isinstance(data, dict):
        return {
            key: _apply_pattern_rules(value, dropped)
            for key, value in data.items()
            if key not in dropped
        }
    return data


def _apply_path_rule(data: Any, path_parts: list[str]) -> Any:
    """Remove the key at the end of the dot-notation path."""
    if not path_parts:
        return data
    if isinstance(data, list):
        return [_apply_path_rule(item, path_parts) for item in data]
    if isinstance(data, dict):
        if len(path_parts) == 1:
            return {k: v for k, v in data.items() if k != path_parts[0]}
        if path_parts[0] in data:
            return {
                **data,
                path_parts[0]: _apply_path_rule(data[path_parts[0]], path_parts[1:]),
            }
    return data


async def _filter_json(data: Any, rules: list[dict[str, str]]) -> Any:
    patterns = [r["value"] for r in rules if r["type"] == "pattern"]
    result = data
    if patterns:
        # The author's patterns run in the isolated worker: one question per distinct key name.
        names = sorted(_key_names(data))
        matched = await match_any(names, patterns)
        dropped = frozenset(n for n, hit in zip(names, matched, strict=True) if hit)
        result = _apply_pattern_rules(data, dropped)
    for rule in rules:
        if rule["type"] == "path":
            result = _apply_path_rule(result, rule["value"].split("."))
    return result


async def _filter_text(text: str, rules: list[dict[str, str]]) -> str:
    patterns = [r["value"] for r in rules if r["type"] == "pattern"]
    if not patterns:
        return text
    lines = text.splitlines(keepends=True)
    matched = await match_any(lines, patterns)
    return "".join(line for line, hit in zip(lines, matched, strict=True) if not hit)


def _select_export_item(
    export_items: list[ExportableContent],
    *,
    parsed: _ParsedFilterConfig,
) -> ExportableContent:
    if parsed.source_command and parsed.content_source == "command_output":
        matched = [i for i in export_items if i.extra.get("command") == parsed.source_command]
        if not matched:
            available = [i.extra.get("command", "") for i in export_items]
            raise ValueError(
                f"Command {parsed.source_command!r} not found in step "
                f"{parsed.source_step_node_id!r}. Available: {available}"
            )
        return matched[0]
    return export_items[0]


async def _filter_content(raw_content: str, media_type: str, rules: Any) -> tuple[str, str]:
    """The filtered text and its media type (JSON stays JSON, anything else is plain text)."""
    if media_type == "application/json":
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Content is not valid JSON: {exc}") from exc
        filtered_content = json.dumps(await _filter_json(data, rules), indent=2)
        if not filtered_content.endswith("\n"):
            filtered_content += "\n"
        return filtered_content, media_type
    return await _filter_text(raw_content, rules), "text/plain"


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions

    parsed = _parse_filter_config(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "filter-output run_id=%s devices=%d source=%s source_node=%s source_command=%r rules=%d",
        log_run_id(run),
        len(context.devices),
        parsed.content_source,
        parsed.source_step_node_id,
        parsed.source_command or "(all)",
        len(parsed.rules),
    )

    async def transform(device_id: str, device: DeviceContext) -> StoredContent:
        export_items = list_exportable_content(
            device,
            content_source=parsed.content_source,
            source_step_node_id=parsed.source_step_node_id,
            step_id=_STEP_ID,
        )
        if not export_items:
            raise ValueError(
                f"No content found for content_source={parsed.content_source!r} "
                f"source_step_node_id={parsed.source_step_node_id!r}"
            )
        item = _select_export_item(export_items, parsed=parsed)
        raw_content = await artifact_service.resolve(item.artifact_ref)
        text, media_type = await _filter_content(raw_content, item.media_type, parsed.rules)
        return StoredContent(text=text, media_type=media_type)

    return await run_content_step(
        context,
        step_id=_STEP_ID,
        node_id=node_id,
        kind="filtered_output",
        transform=transform,
        artifact_service=artifact_service,
        metadata_prefix="filter",
    )
