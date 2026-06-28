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
        "rendered_template",
        "merged_content",
    }
)


def parse_content_source(config: dict[str, Any]) -> str:
    source = str(config.get("content_source") or "").strip().lower()
    if source not in _CONTENT_SOURCES:
        raise ValueError(
            f"store-artifact: content_source {source!r} must be one of "
            f"{sorted(_CONTENT_SOURCES)}"
        )
    return source


def list_exportable_content(
    device: DeviceContext,
    *,
    content_source: str,
    source_step_node_id: str | None = None,
    parsed_output_key: str | None = None,
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

    if content_source == "rendered_template":
        if not source_step_node_id:
            raise ValueError(
                "store-artifact: source_step_node_id is required for rendered_template"
            )
        return _exportable_from_parsed_templates(
            device,
            source_step_node_id=source_step_node_id,
            parsed_output_key=parsed_output_key,
        )

    if content_source == "merged_content":
        if not source_step_node_id:
            raise ValueError(
                "store-artifact: source_step_node_id is required for merged_content"
            )
        return _exportable_from_merged_content(device, source_step_node_id=source_step_node_id)

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


def _is_rendered_template_entry(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    artifact_raw = value.get("artifact_ref")
    if not isinstance(artifact_raw, dict) or not artifact_raw.get("artifact_id"):
        return False
    kind = value.get("kind")
    if kind is not None and kind != "rendered_template":
        return False
    return bool(value.get("step_node_id"))


def _exportable_from_parsed_templates(
    device: DeviceContext,
    *,
    source_step_node_id: str,
    parsed_output_key: str | None = None,
) -> list[ExportableContent]:
    if parsed_output_key:
        raw = device.parsed.get(parsed_output_key)
        candidates = (
            [(parsed_output_key, raw)]
            if raw is not None
            else []
        )
    else:
        candidates = list(device.parsed.items())

    items: list[ExportableContent] = []
    for key, raw in candidates:
        if not _is_rendered_template_entry(raw):
            continue
        if str(raw.get("step_node_id") or "") != source_step_node_id:
            continue
        output_key = str(raw.get("output_key") or key)
        artifact_ref = ArtifactRef.model_validate(raw["artifact_ref"])
        items.append(
            ExportableContent(
                kind="rendered_template",
                media_type=artifact_ref.media_type,
                artifact_ref=artifact_ref,
                extra={
                    "content_source": "rendered_template",
                    "source_step_node_id": source_step_node_id,
                    "output_key": output_key,
                },
            )
        )
    return items


def _exportable_from_merged_content(
    device: DeviceContext,
    *,
    source_step_node_id: str,
) -> list[ExportableContent]:
    key = f"{source_step_node_id}.merged_content"
    raw = device.parsed.get(key)
    if not isinstance(raw, dict):
        return []
    artifact_raw = raw.get("artifact_ref")
    if not isinstance(artifact_raw, dict) or not artifact_raw.get("artifact_id"):
        return []
    if raw.get("kind") != "merged_content":
        return []
    artifact_ref = ArtifactRef.model_validate(artifact_raw)
    return [
        ExportableContent(
            kind="merged_content",
            media_type=artifact_ref.media_type,
            artifact_ref=artifact_ref,
            extra={
                "content_source": "merged_content",
                "source_step_node_id": source_step_node_id,
            },
        )
    ]


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
