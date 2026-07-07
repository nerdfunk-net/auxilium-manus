"""Executor for the show-attributes debugging step."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import settings
from core.models.runs import WorkflowRun
from models.workflow_context import ArtifactRef, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.device_template import sanitize_relative_path
from workflow_steps.show_attributes.config import get_config

logger = logging.getLogger(__name__)

SHOW_ATTRIBUTES_METADATA_SUFFIX = ".show_attributes"
_OUTPUT_DESTINATIONS = frozenset({"stdout", "file"})
_OUTPUT_FORMATS = frozenset({"json", "pretty_text"})
_FILE_APPEND_SEPARATOR = "\n\n---\n\n"


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_bool(config: dict[str, Any], key: str, *, default: bool = False) -> bool:
    value = config.get(key, _default_config().get(key, default))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_config(config: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_config()
    output_destination = str(
        config.get("output_destination") or defaults["output_destination"]
    ).strip().lower()
    if output_destination not in _OUTPUT_DESTINATIONS:
        raise ValueError(
            "show-attributes: output_destination must be 'stdout' or 'file'"
        )

    output_format = str(config.get("output_format") or defaults["output_format"]).strip().lower()
    if output_format not in _OUTPUT_FORMATS:
        raise ValueError(
            "show-attributes: output_format must be 'json' or 'pretty_text'"
        )

    raw_filename = config.get("filename")
    if raw_filename is None:
        raw_filename = defaults["filename"]
    filename = str(raw_filename or "").strip()
    if output_destination == "file" and not filename:
        raise ValueError("show-attributes: filename is required when output_destination=file")

    return {
        "output_destination": output_destination,
        "output_format": output_format,
        "filename": filename,
        "append": _parse_bool(config, "append", default=bool(defaults["append"])),
        "show_parsed_templates": _parse_bool(
            config, "show_parsed_templates", default=bool(defaults["show_parsed_templates"])
        ),
    }


def build_context_snapshot(context: WorkflowContext) -> dict[str, Any]:
    """Serialize the full workflow context envelope for inspection."""
    return context.model_dump(mode="json")


async def _attach_rendered_template_content(
    snapshot: dict[str, Any],
    context: WorkflowContext,
    artifact_service: ArtifactService,
) -> None:
    """Resolve rendered-template artifacts in place so their content is visible in the dump.

    Only entries produced by a "Render Jinja Template" step (``kind ==
    "rendered_template"``) are resolved — other ``device.parsed`` entries
    (e.g. from filter-output/merge-content) are left untouched.
    """
    devices_snapshot = snapshot.get("devices") or {}

    async def resolve_entry(device_snapshot: dict[str, Any], key: str, entry: dict[str, Any]) -> None:
        ref = ArtifactRef.model_validate(entry["artifact_ref"])
        content = await artifact_service.resolve(ref)
        device_snapshot["parsed"][key]["rendered_content"] = content

    tasks = []
    for device_id, device in context.devices.items():
        device_snapshot = devices_snapshot.get(device_id)
        if not isinstance(device_snapshot, dict):
            continue
        for key, entry in device.parsed.items():
            if (
                isinstance(entry, dict)
                and entry.get("kind") == "rendered_template"
                and entry.get("artifact_ref")
            ):
                tasks.append(resolve_entry(device_snapshot, key, entry))

    if tasks:
        await asyncio.gather(*tasks)


def _format_scalar(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _format_block(value: Any, indent: int) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{prefix}(empty)"]
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}{key}:")
                lines.extend(_format_block(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_format_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [f"{prefix}(empty)"]
        lines = []
        for index, item in enumerate(value):
            if isinstance(item, (dict, list)):
                lines.append(f"{prefix}[{index}]:")
                lines.extend(_format_block(item, indent + 2))
            else:
                lines.append(f"{prefix}[{index}]: {_format_scalar(item)}")
        return lines
    return [f"{prefix}{_format_scalar(value)}"]


def format_pretty_text(snapshot: dict[str, Any]) -> str:
    """Render a human-readable dump of the full workflow context."""
    lines = [
        "=== Workflow Context ===",
        f"Run ID: {_format_scalar(snapshot.get('run_id'))}",
        f"Workflow ID: {_format_scalar(snapshot.get('workflow_id'))}",
        f"Schema version: {_format_scalar(snapshot.get('schema_version'))}",
        "",
    ]

    devices = snapshot.get("devices") or {}
    lines.append(f"Devices ({len(devices)}):")
    identity_fields = (
        "id",
        "name",
        "hostname",
        "platform",
        "network_driver",
        "primary_ip4",
        "source",
        "source_id",
    )
    for device_id, device in devices.items():
        if not isinstance(device, dict):
            continue
        lines.append("")
        lines.append(f"--- Device: {device.get('name', device_id)} ({device_id}) ---")
        lines.append("Identity:")
        for field in identity_fields:
            lines.append(f"  {field}: {_format_scalar(device.get(field))}")
        lines.append(f"  capabilities: {', '.join(device.get('capabilities') or [])}")
        lines.append(f"  status: {_format_scalar(device.get('status'))}")

        attribute_bags = device.get("attribute_bags") or {}
        lines.append("Attribute bags:")
        if attribute_bags:
            lines.extend(_format_block(attribute_bags, 2))
        else:
            lines.append("  (none)")

        for section_name, section_key in (
            ("Parsed", "parsed"),
            ("Command results", "command_results"),
            ("Errors", "errors"),
        ):
            section_value = device.get(section_key)
            lines.append(f"{section_name}:")
            if section_value:
                lines.extend(_format_block(section_value, 2))
            else:
                lines.append("  (none)")

        for ref_name, ref_key in (
            ("Running config ref", "running_config_ref"),
            ("Startup config ref", "startup_config_ref"),
        ):
            ref_value = device.get(ref_key)
            if ref_value:
                lines.append(f"{ref_name}:")
                lines.extend(_format_block(ref_value, 2))

    pending_commands = snapshot.get("pending_commands") or {}
    lines.extend(["", "=== Pending commands ==="])
    if pending_commands:
        lines.extend(_format_block(pending_commands, 0))
    else:
        lines.append("(none)")

    metadata = snapshot.get("metadata") or {}
    lines.extend(["", "=== Workflow metadata ==="])
    if metadata:
        lines.extend(_format_block(metadata, 0))
    else:
        lines.append("(none)")

    return "\n".join(lines)


def render_snapshot_text(snapshot: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(snapshot, indent=2, sort_keys=True)
    return format_pretty_text(snapshot)


def _file_target(*, workflow_id: str, run_id: str, filename: str) -> Path:
    safe_name = sanitize_relative_path(filename)
    return (
        settings.data_directory
        / "show-attributes"
        / workflow_id
        / run_id
        / safe_name
    )


def _write_output_file(
    *,
    target: Path,
    content: str,
    append: bool,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if append and target.exists():
        existing = target.read_text(encoding="utf-8")
        payload = f"{existing}{_FILE_APPEND_SEPARATOR}{content}"
    else:
        payload = content
    target.write_text(payload, encoding="utf-8")


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    logger.info("show-attributes started run_id=%s node_id=%s", run.id, node_id)

    parsed = _parse_config(config)
    snapshot = build_context_snapshot(context)
    if parsed["show_parsed_templates"]:
        await _attach_rendered_template_content(snapshot, context, artifact_service)
    rendered = render_snapshot_text(snapshot, parsed["output_format"])
    written_at = datetime.now(timezone.utc).isoformat()

    file_path: str | None = None
    if parsed["output_destination"] == "stdout":
        logger.info(
            "show-attributes node_id=%s format=%s devices=%d\n%s",
            node_id,
            parsed["output_format"],
            len(snapshot.get("devices") or {}),
            rendered,
        )
    else:
        target = _file_target(
            workflow_id=context.workflow_id,
            run_id=context.run_id,
            filename=parsed["filename"],
        )
        _write_output_file(target=target, content=rendered, append=parsed["append"])
        file_path = str(target)
        logger.info(
            "show-attributes node_id=%s wrote file=%s append=%s bytes=%d",
            node_id,
            file_path,
            parsed["append"],
            len(rendered.encode("utf-8")),
        )

    show_attributes = {
        "output_destination": parsed["output_destination"],
        "output_format": parsed["output_format"],
        "filename": parsed["filename"] if parsed["output_destination"] == "file" else None,
        "append": parsed["append"] if parsed["output_destination"] == "file" else None,
        "show_parsed_templates": parsed["show_parsed_templates"],
        "file_path": file_path,
        "written_at": written_at,
        "device_count": len(snapshot.get("devices") or {}),
        "content": rendered,
        "snapshot": snapshot,
    }

    metadata = {
        **context.metadata,
        f"{node_id}{SHOW_ATTRIBUTES_METADATA_SUFFIX}": show_attributes,
    }

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
        )
    ]
