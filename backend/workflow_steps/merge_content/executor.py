"""Executor for the merge-content step."""

from __future__ import annotations

import asyncio
import json
import logging
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

_DEFAULT_SEPARATOR = "\n"
_MERGE_MODES = frozenset({"text_sectioned", "text_plain", "json_merged"})
_CONTENT_SOURCES = frozenset({"command_output", "filtered_output", "merged_content"})


def _parse_content_source(config: dict[str, Any]) -> str:
    source = str(config.get("content_source") or "command_output").strip().lower()
    if source not in _CONTENT_SOURCES:
        raise ValueError(
            f"merge-content: content_source {source!r} must be one of {sorted(_CONTENT_SOURCES)}"
        )
    return source


def _parse_source_step_node_ids(config: dict[str, Any]) -> list[str]:
    raw = config.get("source_step_node_ids")
    if not raw:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return []
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError:
            raw = [s.strip() for s in stripped.split(",") if s.strip()]
    if not isinstance(raw, list):
        return []
    return [str(v).strip() for v in raw if str(v).strip()]


def _parse_merge_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("merge_mode") or "text_sectioned").strip().lower()
    if mode not in _MERGE_MODES:
        raise ValueError(
            f"merge-content: merge_mode {mode!r} must be one of {sorted(_MERGE_MODES)}"
        )
    return mode


def _parse_include_command_header(config: dict[str, Any]) -> bool:
    value = config.get("include_command_header", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _merged_content_entry(
    *,
    artifact_ref: Any,
    node_id: str,
    size_bytes: int,
) -> dict[str, Any]:
    return {
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "step_node_id": node_id,
        "output_key": "merged_content",
        "size_bytes": size_bytes,
        "kind": "merged_content",
    }


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

    content_source = _parse_content_source(config)
    source_node_ids = _parse_source_step_node_ids(config)
    merge_mode = _parse_merge_mode(config)
    section_separator = str(config.get("section_separator") or _DEFAULT_SEPARATOR)
    include_command_header = _parse_include_command_header(config)

    if content_source != "command_output" and not source_node_ids:
        raise ValueError(
            f"merge-content: source_step_node_ids is required when content_source={content_source!r}"
        )

    logger.info(
        "merge-content run_id=%s devices=%d mode=%s content_source=%s sources=%r",
        run.id,
        len(context.devices),
        merge_mode,
        content_source,
        source_node_ids or "all",
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def merge_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            items: list[tuple[str, str, str]] = []

            if content_source == "command_output":
                if source_node_ids:
                    node_ids_to_use = [n for n in source_node_ids if n in device.command_results]
                else:
                    node_ids_to_use = list(device.command_results.keys())

                for src_node_id in node_ids_to_use:
                    for result in device.command_results.get(src_node_id, []):
                        if result.output_ref is None:
                            continue
                        text = await artifact_service.resolve(result.output_ref)
                        items.append((result.command, text, result.output_ref.media_type))
            else:
                for src_node_id in source_node_ids:
                    export_items = list_exportable_content(
                        device,
                        content_source=content_source,
                        source_step_node_id=src_node_id,
                    )
                    for export_item in export_items:
                        text = await artifact_service.resolve(export_item.artifact_ref)
                        items.append((src_node_id, text, export_item.media_type))

            if merge_mode == "text_sectioned":
                blocks: list[str] = []
                for command, text, _ in items:
                    if include_command_header:
                        blocks.append(f"=== {command} ===\n{text}")
                    else:
                        blocks.append(text)
                merged_str = section_separator.join(blocks)
                merged_media_type = "text/plain"

            elif merge_mode == "text_plain":
                merged_str = section_separator.join(text for _, text, _ in items)
                merged_media_type = "text/plain"

            else:  # json_merged
                merged_obj: dict[str, Any] = {}
                for command, text, media_type in items:
                    if media_type == "application/json":
                        try:
                            merged_obj[command] = json.loads(text)
                        except json.JSONDecodeError:
                            merged_obj[command] = text
                    else:
                        merged_obj[command] = text
                merged_str = json.dumps(merged_obj, indent=2)
                merged_media_type = "application/json"

            if not merged_str.endswith("\n"):
                merged_str += "\n"

            artifact_ref = await artifact_service.store(
                content=merged_str,
                kind="merged_content",
                device_id=device_id,
                run_id=context.run_id,
                media_type=merged_media_type,
            )

            size_bytes = len(merged_str.encode("utf-8"))
            updated_parsed = dict(device.parsed)
            updated_parsed[f"{node_id}.merged_content"] = _merged_content_entry(
                artifact_ref=artifact_ref,
                node_id=node_id,
                size_bytes=size_bytes,
            )

            enriched = device.model_copy(
                update={
                    "parsed": updated_parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True

        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="merge-content",
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
        *[merge_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "merge-content returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

    metadata = {
        **context.metadata,
        f"{node_id}.merged_content_mode": merge_mode,
        f"{node_id}.merged_success_count": len(success_devices),
        f"{node_id}.merged_failure_count": len(failed_devices),
    }

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices, "metadata": metadata}),
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
