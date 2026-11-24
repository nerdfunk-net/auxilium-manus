"""Resolve exportable content from a device WorkflowContext."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from models.failure import FailureInfo
from models.workflow_context import ArtifactRef, CommandResult, DeviceContext
from services.workflow_context.node_result import get_node_result


@dataclass(frozen=True)
class ExportableContent:
    """One blob ready to be written by store-artifact."""

    kind: str
    media_type: str
    artifact_ref: ArtifactRef
    extra: dict[str, Any]


CONTENT_SOURCES = frozenset(
    {
        "running_config",
        "startup_config",
        "command_output",
        "latest_command_output",
        "rendered_template",
        "merged_content",
        "comparison_diff",
        "filtered_output",
        "pyats_snapshot",
        "updated_content",
    }
)


def ambiguous_content_message(count: int) -> str:
    return (
        f"{count} exportable items found; use one command per run-command step or select a "
        "single source step"
    )


AMBIGUOUS_CONTENT_FAILURE = FailureInfo(phase="command", kind="ambiguous_match")
AMBIGUOUS_CONTENT_CODE = "ambiguous_content"


def single_item_or_message(items: Sequence[ExportableContent]) -> str | None:
    """``None`` when ``items`` holds at most one entry, else the shared "ambiguous" message."""
    return ambiguous_content_message(len(items)) if len(items) > 1 else None


def parse_content_source(
    config: dict[str, Any],
    *,
    step_id: str,
    default: str = "",
    allowed: frozenset[str] = CONTENT_SOURCES,
) -> str:
    """The configured ``content_source``; a blank one takes ``default`` (the step's own
    ``get_config()`` value), a value outside ``allowed`` is an error naming ``step_id``."""
    source = str(config.get("content_source") or default).strip().lower()
    if source not in allowed:
        raise ValueError(f"{step_id}: content_source {source!r} must be one of {sorted(allowed)}")
    return source


# Sources a step stored as ``parsed[<node>][<source>]``, each with the entry keys copied into
# ``extra`` besides ``content_source`` and ``source_step_node_id``. ``kind`` of the entry must
# equal the source: it is how a consumer tells the entries of different producers apart.
_NODE_RESULT_SOURCES: dict[str, tuple[str, ...]] = {
    "merged_content": (),
    "comparison_diff": ("reference_path",),
    "filtered_output": (),
    "updated_content": (),
}

_NEEDS_SOURCE_NODE = frozenset(
    {"command_output", "rendered_template", "pyats_snapshot", *_NODE_RESULT_SOURCES}
)


def list_exportable_content(
    device: DeviceContext,
    *,
    content_source: str,
    step_id: str,
    source_step_node_id: str | None = None,
    parsed_output_key: str | None = None,
) -> list[ExportableContent]:
    """Return artifact refs available on the device for the chosen source."""
    if content_source in _NEEDS_SOURCE_NODE and not source_step_node_id:
        raise ValueError(f"{step_id}: source_step_node_id is required for {content_source}")

    if content_source in ("running_config", "startup_config"):
        ref = (
            device.running_config_ref
            if content_source == "running_config"
            else device.startup_config_ref
        )
        if ref is None:
            return []
        return [
            ExportableContent(
                kind=content_source,
                media_type=ref.media_type,
                artifact_ref=ref,
                extra={"content_source": content_source},
            )
        ]

    if content_source == "command_output":
        results = device.command_results.get(source_step_node_id or "", [])
        return _exportable_from_command_results(
            results, source_step_node_id=source_step_node_id or ""
        )

    if content_source == "latest_command_output":
        latest = _latest_command_result(device)
        if latest is None:
            return []
        node_id, result = latest
        return _exportable_from_command_results([result], source_step_node_id=node_id)

    if content_source == "rendered_template":
        return _exportable_from_parsed_templates(
            device,
            source_step_node_id=source_step_node_id or "",
            parsed_output_key=parsed_output_key,
        )

    if content_source == "pyats_snapshot":
        return _exportable_from_pyats_snapshot(
            device,
            source_step_node_id=source_step_node_id or "",
            parsed_output_key=parsed_output_key,
        )

    if content_source in _NODE_RESULT_SOURCES:
        return _exportable_from_node_result(
            device, content_source, source_step_node_id=source_step_node_id or ""
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
        candidates = [(parsed_output_key, raw)] if raw is not None else []
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


def _is_pyats_snapshot_entry(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("kind") != "pyats_snapshot":
        return False
    artifact_raw = value.get("artifact_ref")
    if not isinstance(artifact_raw, dict) or not artifact_raw.get("artifact_id"):
        return False
    return bool(value.get("step_node_id"))


def _exportable_from_pyats_snapshot(
    device: DeviceContext,
    *,
    source_step_node_id: str,
    parsed_output_key: str | None = None,
) -> list[ExportableContent]:
    if parsed_output_key:
        raw = device.parsed.get(parsed_output_key)
        candidates = [(parsed_output_key, raw)] if raw is not None else []
    else:
        candidates = list(device.parsed.items())

    items: list[ExportableContent] = []
    for key, raw in candidates:
        if not _is_pyats_snapshot_entry(raw):
            continue
        if str(raw.get("step_node_id") or "") != source_step_node_id:
            continue
        output_key = str(raw.get("output_key") or key)
        artifact_ref = ArtifactRef.model_validate(raw["artifact_ref"])
        features = raw.get("features") if isinstance(raw.get("features"), dict) else {}
        items.append(
            ExportableContent(
                kind="pyats_snapshot",
                media_type=artifact_ref.media_type,
                artifact_ref=artifact_ref,
                extra={
                    "content_source": "pyats_snapshot",
                    "source_step_node_id": source_step_node_id,
                    "output_key": output_key,
                    "features": sorted(features.keys()),
                },
            )
        )
    return items


def _exportable_from_node_result(
    device: DeviceContext, source: str, *, source_step_node_id: str
) -> list[ExportableContent]:
    raw = get_node_result(device.parsed, source_step_node_id, source)
    if not isinstance(raw, dict):
        return []
    artifact_raw = raw.get("artifact_ref")
    if not isinstance(artifact_raw, dict) or not artifact_raw.get("artifact_id"):
        return []
    if raw.get("kind") != source:
        return []
    artifact_ref = ArtifactRef.model_validate(artifact_raw)
    extra: dict[str, Any] = {"content_source": source, "source_step_node_id": source_step_node_id}
    extra.update({key: raw.get(key) for key in _NODE_RESULT_SOURCES[source]})
    return [
        ExportableContent(
            kind=source, media_type=artifact_ref.media_type, artifact_ref=artifact_ref, extra=extra
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
