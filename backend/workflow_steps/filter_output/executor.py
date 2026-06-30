"""Executor for the filter-output step.

Reads command output or merged content from an upstream step, applies user-configured
filter rules to remove volatile or irrelevant fields, and stores the cleaned result in
device.parsed so downstream compare-data and store-artifact steps can consume it.

Filter rules:
  - pattern: regex matched against JSON key names (recursive) or text lines.
  - path: dot-notation path ("route.ospf") to a specific JSON key to remove.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.content_resolver import list_exportable_content

logger = logging.getLogger(__name__)

_SUPPORTED_SOURCES = frozenset({"command_output", "merged_content"})


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
            raise ValueError(
                f"filter-output: filter_rules[{i}] must have 'pattern' or 'path'"
            )
        if has_pattern:
            pattern = str(item["pattern"]).strip()
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(
                    f"filter-output: filter_rules[{i}].pattern {pattern!r} is not valid regex: {exc}"
                ) from exc
            rules.append({"type": "pattern", "value": pattern})
        else:
            rules.append({"type": "path", "value": str(item["path"]).strip()})
    return rules


def _apply_pattern_rules(data: Any, patterns: list[str]) -> Any:
    """Recursively remove object keys whose names match any pattern."""
    if isinstance(data, list):
        return [_apply_pattern_rules(item, patterns) for item in data]
    if isinstance(data, dict):
        return {
            key: _apply_pattern_rules(value, patterns)
            for key, value in data.items()
            if not any(re.search(p, key) for p in patterns)
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


def _filter_json(data: Any, rules: list[dict[str, str]]) -> Any:
    patterns = [r["value"] for r in rules if r["type"] == "pattern"]
    result = _apply_pattern_rules(data, patterns) if patterns else data
    for rule in rules:
        if rule["type"] == "path":
            result = _apply_path_rule(result, rule["value"].split("."))
    return result


def _filter_text(text: str, rules: list[dict[str, str]]) -> str:
    patterns = [r["value"] for r in rules if r["type"] == "pattern"]
    if not patterns:
        return text
    lines = text.splitlines(keepends=True)
    return "".join(
        line for line in lines if not any(re.search(p, line) for p in patterns)
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

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

    logger.info(
        "filter-output run_id=%s devices=%d source=%s source_node=%s source_command=%r rules=%d",
        run.id,
        len(context.devices),
        content_source,
        source_step_node_id,
        source_command or "(all)",
        len(rules),
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def filter_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            export_items = list_exportable_content(
                device,
                content_source=content_source,
                source_step_node_id=source_step_node_id,
            )
            if not export_items:
                raise ValueError(
                    f"No content found for content_source={content_source!r} "
                    f"source_step_node_id={source_step_node_id!r}"
                )

            if source_command and content_source == "command_output":
                matched = [
                    i for i in export_items if i.extra.get("command") == source_command
                ]
                if not matched:
                    available = [i.extra.get("command", "") for i in export_items]
                    raise ValueError(
                        f"Command {source_command!r} not found in step "
                        f"{source_step_node_id!r}. Available: {available}"
                    )
                item = matched[0]
            else:
                item = export_items[0]
            raw_content = await artifact_service.resolve(item.artifact_ref)
            media_type = item.media_type

            if media_type == "application/json":
                try:
                    data = json.loads(raw_content)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Content is not valid JSON: {exc}") from exc
                filtered_data = _filter_json(data, rules)
                filtered_content = json.dumps(filtered_data, indent=2)
                if not filtered_content.endswith("\n"):
                    filtered_content += "\n"
            else:
                filtered_content = _filter_text(raw_content, rules)
                media_type = "text/plain"

            artifact_ref = await artifact_service.store(
                content=filtered_content,
                kind="filtered_output",
                device_id=device_id,
                run_id=context.run_id,
                media_type=media_type,
            )

            size_bytes = len(filtered_content.encode("utf-8"))
            updated_parsed = {
                **device.parsed,
                f"{node_id}.filtered_output": {
                    "artifact_ref": artifact_ref.model_dump(mode="json"),
                    "step_node_id": node_id,
                    "output_key": "filtered_output",
                    "size_bytes": size_bytes,
                    "kind": "filtered_output",
                },
            }

            enriched = device.model_copy(
                update={
                    "parsed": updated_parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True

        except Exception as exc:
            logger.warning("filter-output device=%s error=%s", device_id, exc)
            err = DeviceError(
                node_id=node_id,
                step_id="filter-output",
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False

    results = await asyncio.gather(
        *[filter_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "filter-output returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    metadata = {
        **context.metadata,
        f"{node_id}.filter_success_count": len(success_devices),
        f"{node_id}.filter_failure_count": len(failed_devices),
    }

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(
                update={"devices": success_devices, "metadata": metadata}
            ),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
            )
        )
    return outcomes
