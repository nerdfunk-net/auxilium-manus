"""Executor for the log-attributes debugging step."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import ArtifactRef, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.execution.log_attribute_files import log_attributes_root
from services.workflow_context.config_scrub import scrub_config_text
from services.workflow_context.device_template import sanitize_relative_path
from services.workflow_context.secret_fields import redact_secrets_in_data
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.log_attributes.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_METADATA_SUFFIX = ".log_attributes"
_OUTPUT_DESTINATIONS = frozenset({"stdout", "file"})
_OUTPUT_FORMATS = frozenset({"json", "pretty_text"})
_FILE_APPEND_SEPARATOR = "\n\n---\n\n"


@dataclass(frozen=True)
class _LogAttributesConfig:
    output_destination: str
    output_format: str
    filename: str
    append: bool
    show_parsed_templates: bool
    show_device_configs: bool


def _parse_config(config: dict[str, Any]) -> _LogAttributesConfig:
    defaults = get_config()
    output_destination = (
        str(config.get("output_destination") or defaults["output_destination"]).strip().lower()
    )
    if output_destination not in _OUTPUT_DESTINATIONS:
        raise ValueError("log-attributes: output_destination must be 'stdout' or 'file'")

    output_format = str(config.get("output_format") or defaults["output_format"]).strip().lower()
    if output_format not in _OUTPUT_FORMATS:
        raise ValueError("log-attributes: output_format must be 'json' or 'pretty_text'")

    raw_filename = config.get("filename")
    if raw_filename is None:
        raw_filename = defaults["filename"]
    filename = str(raw_filename or "").strip()
    if output_destination == "file" and not filename:
        raise ValueError("log-attributes: filename is required when output_destination=file")

    return _LogAttributesConfig(
        output_destination=output_destination,
        output_format=output_format,
        filename=filename,
        append=parse_bool_flag(config, "append", default=bool(defaults["append"])),
        show_parsed_templates=parse_bool_flag(
            config, "show_parsed_templates", default=bool(defaults["show_parsed_templates"])
        ),
        show_device_configs=parse_bool_flag(
            config, "show_device_configs", default=bool(defaults["show_device_configs"])
        ),
    )


def build_context_snapshot(context: WorkflowContext) -> dict[str, Any]:
    """Serialize the workflow context envelope for inspection, with secrets redacted."""
    return redact_secrets_in_data(context.model_dump(mode="json"))


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

    async def resolve_entry(
        device_snapshot: dict[str, Any], key: str, entry: dict[str, Any]
    ) -> None:
        ref = ArtifactRef.model_validate(entry["artifact_ref"])
        content = await artifact_service.resolve(ref)
        device_snapshot["parsed"][key]["rendered_content"] = scrub_config_text(content)

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


async def _attach_device_config_content(
    snapshot: dict[str, Any],
    context: WorkflowContext,
    artifact_service: ArtifactService,
) -> None:
    """Resolve running/startup config artifacts so their content is visible in the dump.

    Only devices that carry ``running_config_ref`` and/or ``startup_config_ref``
    (typically from an upstream Get Device Configs step) are resolved. Missing
    refs are left alone.
    """
    devices_snapshot = snapshot.get("devices") or {}

    async def resolve_config(
        device_snapshot: dict[str, Any],
        *,
        ref: ArtifactRef,
        content_key: str,
    ) -> None:
        # Best effort: the artifact itself stays verbatim, the attached copy is masked.
        content = await artifact_service.resolve(ref)
        device_snapshot[content_key] = scrub_config_text(content)

    tasks = []
    for device_id, device in context.devices.items():
        device_snapshot = devices_snapshot.get(device_id)
        if not isinstance(device_snapshot, dict):
            continue
        if device.running_config_ref is not None:
            tasks.append(
                resolve_config(
                    device_snapshot,
                    ref=device.running_config_ref,
                    content_key="running_config_content",
                )
            )
        if device.startup_config_ref is not None:
            tasks.append(
                resolve_config(
                    device_snapshot,
                    ref=device.startup_config_ref,
                    content_key="startup_config_content",
                )
            )

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


_IDENTITY_FIELDS = (
    "id",
    "name",
    "hostname",
    "platform",
    "network_driver",
    "primary_ip4",
    "source",
    "source_id",
)
_DEVICE_SECTIONS = (
    ("Parsed", "parsed"),
    ("Command results", "command_results"),
    ("Errors", "errors"),
)
_CONFIG_REFS = (
    ("Running config ref", "running_config_ref"),
    ("Startup config ref", "startup_config_ref"),
)
_CONFIG_CONTENTS = (
    ("Running config", "running_config_content"),
    ("Startup config", "startup_config_content"),
)


def _block_or_none(value: Any, indent: int) -> list[str]:
    """``value`` as an indented block, or ``(none)`` at that indent when it is empty."""
    return _format_block(value, indent) if value else [f"{' ' * indent}(none)"]


def _identity_lines(device: dict[str, Any]) -> list[str]:
    lines = ["Identity:"]
    lines.extend(f"  {field}: {_format_scalar(device.get(field))}" for field in _IDENTITY_FIELDS)
    lines.append(f"  capabilities: {', '.join(device.get('capabilities') or [])}")
    lines.append(f"  status: {_format_scalar(device.get('status'))}")
    return lines


def _config_lines(device: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for ref_name, ref_key in _CONFIG_REFS:
        ref_value = device.get(ref_key)
        if ref_value:
            lines.append(f"{ref_name}:")
            lines.extend(_format_block(ref_value, 2))
    for content_name, content_key in _CONFIG_CONTENTS:
        content_value = device.get(content_key)
        if content_value is not None:
            lines.append(f"{content_name}:")
            # Keep multi-line config bodies readable — dump as indented text.
            lines.extend(f"  {line}" for line in str(content_value).splitlines() or [""])
    return lines


def _device_lines(device_id: str, device: dict[str, Any]) -> list[str]:
    lines = ["", f"--- Device: {device.get('name', device_id)} ({device_id}) ---"]
    lines.extend(_identity_lines(device))
    lines.append("Attribute bags:")
    lines.extend(_block_or_none(device.get("attribute_bags"), 2))
    for section_name, section_key in _DEVICE_SECTIONS:
        lines.append(f"{section_name}:")
        lines.extend(_block_or_none(device.get(section_key), 2))
    lines.extend(_config_lines(device))
    return lines


def format_pretty_text(snapshot: dict[str, Any]) -> str:
    """Render a human-readable dump of the full workflow context."""
    devices = snapshot.get("devices") or {}
    lines = [
        "=== Workflow Context ===",
        f"Run ID: {_format_scalar(snapshot.get('run_id'))}",
        f"Workflow ID: {_format_scalar(snapshot.get('workflow_id'))}",
        f"Schema version: {_format_scalar(snapshot.get('schema_version'))}",
        "",
        f"Devices ({len(devices)}):",
    ]
    for device_id, device in devices.items():
        if isinstance(device, dict):
            lines.extend(_device_lines(device_id, device))
    for title, key in (("Pending commands", "pending_commands"), ("Workflow metadata", "metadata")):
        lines.extend(["", f"=== {title} ==="])
        lines.extend(_block_or_none(snapshot.get(key), 0))
    return "\n".join(lines)


def render_snapshot_text(snapshot: dict[str, Any], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(snapshot, indent=2, sort_keys=True)
    return format_pretty_text(snapshot)


def _file_target(*, workflow_id: str, run_id: str, filename: str) -> Path:
    safe_name = sanitize_relative_path(filename)
    return log_attributes_root() / workflow_id / run_id / safe_name


def _write_output_file(
    *,
    target: Path,
    content: str,
    append: bool,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if append:
        # O_APPEND: concurrent writers (fan-out children) do not lose each other's entries.
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"{_FILE_APPEND_SEPARATOR}{content}" if handle.tell() else content)
    else:
        target.write_text(content, encoding="utf-8")


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    parsed = _parse_config(config)
    logger.info("log-attributes started run_id=%s node_id=%s", log_run_id(run), node_id)
    snapshot = build_context_snapshot(context)
    if parsed.show_parsed_templates:
        await _attach_rendered_template_content(snapshot, context, artifact_service)
    if parsed.show_device_configs:
        await _attach_device_config_content(snapshot, context, artifact_service)
    # Rendering and the file write are CPU- and disk-bound: off the event loop (W4-15).
    rendered = await asyncio.to_thread(render_snapshot_text, snapshot, parsed.output_format)
    written_at = datetime.now(UTC).isoformat()

    file_path: str | None = None
    if parsed.output_destination == "stdout":
        logger.info(
            "log-attributes node_id=%s format=%s devices=%d\n%s",
            node_id,
            parsed.output_format,
            len(snapshot.get("devices") or {}),
            rendered,
        )
    else:
        target = _file_target(
            workflow_id=context.workflow_id,
            run_id=context.run_id,
            filename=parsed.filename,
        )
        await asyncio.to_thread(
            _write_output_file, target=target, content=rendered, append=parsed.append
        )
        file_path = str(target)
        logger.info(
            "log-attributes node_id=%s wrote file=%s append=%s bytes=%d",
            node_id,
            file_path,
            parsed.append,
            len(rendered.encode("utf-8")),
        )

    log_attributes = {
        "output_destination": parsed.output_destination,
        "output_format": parsed.output_format,
        "filename": parsed.filename if parsed.output_destination == "file" else None,
        "append": parsed.append if parsed.output_destination == "file" else None,
        "show_parsed_templates": parsed.show_parsed_templates,
        "show_device_configs": parsed.show_device_configs,
        "file_path": file_path,
        "written_at": written_at,
        "device_count": len(snapshot.get("devices") or {}),
        "content": rendered,
        "snapshot": snapshot,
    }

    metadata = {
        **context.metadata,
        f"{node_id}{_METADATA_SUFFIX}": log_attributes,
    }

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
        )
    ]
