"""Render filename templates from device context fields."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from models.workflow_context import DeviceContext

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_.]+)\}")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


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


def build_template_context(
    device: DeviceContext,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    primary_ip4 = device.primary_ip4.split("/")[0] if device.primary_ip4 else ""
    context: dict[str, Any] = {
        "name": device.name,
        "hostname": device.hostname,
        "id": device.id,
        "primary_ip4": primary_ip4,
        "platform": device.platform or "",
        "network_driver": device.network_driver or "",
        "source": device.source,
        "source_id": device.source_id,
        "attributes": device.attributes,
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
    }
    if extra:
        context.update(extra)
    return context


def render_device_template(
    template: str,
    device: DeviceContext,
    *,
    extra: dict[str, Any] | None = None,
) -> str:
    """Replace ``{name}``, ``{attributes.location.name}``, etc. in a filename template."""
    context = build_template_context(device, extra=extra)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if "." not in key and key in context:
            return _stringify(context[key])
        nested = _traverse_path(context, key)
        return _stringify(nested)

    rendered = _PLACEHOLDER_RE.sub(replace, template).strip()
    if not rendered:
        raise ValueError("filename template rendered to an empty string")
    return sanitize_filename(rendered)


def sanitize_filename(filename: str) -> str:
    """Remove characters that are unsafe on common filesystems."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", filename)
    cleaned = cleaned.replace("..", "_").strip().strip(".")
    if not cleaned:
        raise ValueError("filename is empty after sanitization")
    return cleaned
