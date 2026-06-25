"""Render filename templates from namespaced device context fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from models.workflow_context import DeviceContext

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_.]+)\}")
_INVALID_SEGMENT_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_STRICT_PREFIXES = ("nautobot.", "git.", "command.")
_KNOWN_NAMESPACES = ("device", "nautobot", "git", "run", "command")


class TemplateResolutionError(ValueError):
    """Raised when a template placeholder cannot be resolved in strict mode."""


@dataclass(frozen=True)
class TemplateRenderOptions:
    strict: bool = True
    run_id: str | None = None


def _traverse_path(root: Any, path: str) -> Any:
    current = root
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
            continue
        return None
    return current


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return ""
    return str(value).strip()


def _is_strict_placeholder(key: str) -> bool:
    return key.startswith(_STRICT_PREFIXES)


def build_template_context(
    device: DeviceContext,
    *,
    run_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the namespaced lookup tree for template placeholders."""
    primary_ip4 = device.primary_ip4.split("/")[0] if device.primary_ip4 else ""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    command_bag: dict[str, Any] = {}
    if extra:
        if "command" in extra:
            command_bag["name"] = extra.get("command")
        if "index" in extra:
            command_bag["index"] = extra.get("index")
        if "source_step_node_id" in extra:
            command_bag["source_step_node_id"] = extra.get("source_step_node_id")

    return {
        "device": {
            "name": device.name,
            "hostname": device.hostname,
            "id": device.id,
            "primary_ip4": primary_ip4,
            "platform": device.platform or "",
            "network_driver": device.network_driver or "",
            "source": device.source,
            "source_id": device.source_id,
        },
        "nautobot": dict(device.attribute_bags.get("nautobot", {})),
        "git": dict(device.attribute_bags.get("git", {})),
        "run": {
            "id": run_id or "",
            "timestamp": timestamp,
        },
        "command": command_bag,
    }


def _resolve_placeholder(context: dict[str, Any], key: str) -> str:
    namespace = key.split(".", 1)[0] if "." in key else ""
    if namespace and namespace not in _KNOWN_NAMESPACES:
        return ""
    return _stringify(_traverse_path(context, key))


def _validate_strict_resolution(
    *,
    key: str,
    value: str,
    context: dict[str, Any],
) -> None:
    if not _is_strict_placeholder(key):
        return
    if value:
        return

    namespace = key.split(".", 1)[0]
    bag = context.get(namespace)
    if namespace == "nautobot" and not bag:
        raise TemplateResolutionError(
            f"Template placeholder {{{key}}} requires Nautobot attributes, but none "
            "are present on this device. Add get-nautobot-attributes upstream."
        )
    if namespace == "git" and not bag:
        raise TemplateResolutionError(
            f"Template placeholder {{{key}}} requires git attributes, but none "
            "are present on this device. Add get-git-devices upstream."
        )
    if namespace == "command":
        raise TemplateResolutionError(
            f"Template placeholder {{{key}}} resolved empty. Ensure command output is "
            "available for this export."
        )

    raise TemplateResolutionError(
        f"Template placeholder {{{key}}} resolved empty. Check the attribute path "
        f"in the device {namespace} attribute bag."
    )


def render_device_template(
    template: str,
    device: DeviceContext,
    *,
    extra: dict[str, Any] | None = None,
    options: TemplateRenderOptions | None = None,
) -> str:
    """Replace placeholders and return a safe relative path or filename."""
    render_options = options or TemplateRenderOptions()
    context = build_template_context(
        device,
        run_id=render_options.run_id,
        extra=extra,
    )

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = _resolve_placeholder(context, key)
        if render_options.strict:
            _validate_strict_resolution(key=key, value=value, context=context)
        return value

    rendered = _PLACEHOLDER_RE.sub(replace, template).strip()
    if not rendered:
        raise TemplateResolutionError("filename template rendered to an empty string")
    return sanitize_relative_path(rendered)


def sanitize_path_segment(segment: str) -> str:
    """Remove characters that are unsafe in a single path component."""
    cleaned = _INVALID_SEGMENT_CHARS.sub("_", segment)
    cleaned = cleaned.replace("..", "_").strip().strip(".")
    if not cleaned:
        raise ValueError("path segment is empty after sanitization")
    return cleaned


def sanitize_relative_path(relative_path: str) -> str:
    """Normalize and sanitize a relative export path (may include subdirectories)."""
    normalized = relative_path.replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")

    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts:
        raise ValueError("relative path is empty after normalization")
    if ".." in parts:
        raise ValueError("relative path must not contain parent directory segments")

    return "/".join(sanitize_path_segment(part) for part in parts)


def sanitize_filename(filename: str) -> str:
    """Sanitize a single filename or a relative path with directory segments."""
    if "/" in filename or "\\" in filename:
        return sanitize_relative_path(filename)
    return sanitize_path_segment(filename)


def parse_strict_templates(config: dict[str, Any]) -> bool:
    value = config.get("strict_templates", True)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


_STEP_TEMPLATE_ALIASES = {
    "timestamp": "run.timestamp",
    "workflow_id": "workflow.id",
}


def render_step_template(
    template: str,
    *,
    run_id: str,
    workflow_id: str | None = None,
) -> str:
    """Render run/workflow placeholders for step-level messages (e.g. git commits)."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    context: dict[str, Any] = {
        "run": {"id": run_id, "timestamp": timestamp},
        "workflow": {"id": workflow_id or ""},
        "timestamp": timestamp,
    }

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        normalized = _STEP_TEMPLATE_ALIASES.get(key, key)
        return _stringify(_traverse_path(context, normalized))

    rendered = _PLACEHOLDER_RE.sub(replace, template).strip()
    if not rendered:
        raise TemplateResolutionError("step template rendered to an empty string")
    return rendered
