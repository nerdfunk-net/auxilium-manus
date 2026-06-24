"""Resolve exportable content from a device WorkflowContext."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models.workflow_context import ArtifactRef, CommandResult, DeviceContext


@dataclass(frozen=True)
class ExportableContent:
    """One blob ready to be written by store-artifact."""

    kind: str
    media_type: str
    artifact_ref: ArtifactRef
    extra: dict[str, Any]


_CONTENT_SOURCES = frozenset(
    {
        "running_config",
        "startup_config",
        "command_output",
        "latest_command_output",
    }
)


def parse_content_source(config: dict[str, Any]) -> str:
    source = str(config.get("content_source") or "").strip().lower()
    if source not in _CONTENT_SOURCES:
        raise ValueError(
            f"store-artifact: content_source must be one of {sorted(_CONTENT_SOURCES)}"
        )
    return source


def list_exportable_content(
    device: DeviceContext,
    *,
    content_source: str,
    source_step_node_id: str | None = None,
) -> list[ExportableContent]:
    """Return artifact refs available on the device for the chosen source."""
    if content_source == "running_config":
        if device.running_config_ref is None:
            return []
        return [
            ExportableContent(
                kind="running_config",
                media_type=device.running_config_ref.media_type,
                artifact_ref=device.running_config_ref,
                extra={"content_source": content_source},
            )
        ]

    if content_source == "startup_config":
        if device.startup_config_ref is None:
            return []
        return [
            ExportableContent(
                kind="startup_config",
                media_type=device.startup_config_ref.media_type,
                artifact_ref=device.startup_config_ref,
                extra={"content_source": content_source},
            )
        ]

    if content_source == "command_output":
        if not source_step_node_id:
            raise ValueError(
                "store-artifact: source_step_node_id is required for command_output"
            )
        results = device.command_results.get(source_step_node_id, [])
        return _exportable_from_command_results(
            results,
            source_step_node_id=source_step_node_id,
        )

    if content_source == "latest_command_output":
        latest = _latest_command_result(device)
        if latest is None:
            return []
        node_id, result = latest
        return _exportable_from_command_results(
            [result],
            source_step_node_id=node_id,
        )

    return []


def _exportable_from_command_results(
    results: list[CommandResult],
    *,
    source_step_node_id: str,
) -> list[ExportableContent]:
    items: list[ExportableContent] = []
    for result in results:
        if result.output_ref is None:
            continue
        items.append(
            ExportableContent(
                kind="command_output",
                media_type=result.output_ref.media_type,
                artifact_ref=result.output_ref,
                extra={
                    "content_source": "command_output",
                    "source_step_node_id": source_step_node_id,
                    "command": result.command,
                },
            )
        )
    return items


def _latest_command_result(
    device: DeviceContext,
) -> tuple[str, CommandResult] | None:
    latest: tuple[str, CommandResult] | None = None
    for node_id, results in device.command_results.items():
        for result in results:
            if result.output_ref is None:
                continue
            if latest is None or result.executed_at > latest[1].executed_at:
                latest = (node_id, result)
    return latest
