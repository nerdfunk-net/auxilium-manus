"""Resolve update-nautobot-device field value expressions against device context."""

from __future__ import annotations

import re
from typing import Any

from models.workflow_context import DeviceContext
from workflow_steps.common.attribute_path import resolve_device_attribute, resolve_device_value
from workflow_steps.common.nautobot_update_fields import (
    extract_update_fields_from_nautobot_bag,
)

_DEVICE_FIELD_KEYS = frozenset(
    {
        "name",
        "location",
        "serial",
        "role",
        "status",
        "device_type",
        "platform",
        "software_version",
        "asset_tag",
        "tags",
        "custom_fields",
        "primary_ip4",
        "rack",
        "position",
        "face",
    }
)

_BRACE_EXPRESSION = re.compile(
    r"^\{\s*"
    r"(?P<path>nautobot\.origin|[^}|]+?)"
    r"(?:\s*\|\s*default\(\s*(?P<quote>['\"])(?P<default>.*?)(?P=quote)\s*\))?"
    r"\s*\}$"
)


def normalize_field_spec(raw: Any) -> tuple[bool, str]:
    """Return (enabled, value_expression) from config field data."""
    if isinstance(raw, dict):
        enabled = bool(raw.get("enabled"))
        value = str(raw.get("value") or "")
        return enabled, value

    if isinstance(raw, list):
        cleaned = [str(item).strip() for item in raw if str(item).strip()]
        if cleaned:
            return True, ", ".join(cleaned)
        return False, ""

    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped:
            return True, stripped
        return False, ""

    return False, ""


def config_has_enabled_update_fields(raw_fields: Any) -> bool:
    """Return True when update_fields contains at least one enabled entry."""
    if not isinstance(raw_fields, dict):
        return False

    for key, raw in raw_fields.items():
        if key == "custom_fields":
            if not isinstance(raw, dict):
                continue
            for cf_raw in raw.values():
                enabled, _ = normalize_field_spec(cf_raw)
                if enabled:
                    return True
            continue

        if key not in _DEVICE_FIELD_KEYS:
            continue
        enabled, _ = normalize_field_spec(raw)
        if enabled:
            return True
    return False


def _stringify_resolved(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _resolve_nautobot_origin(
    device: DeviceContext,
    field_key: str,
    *,
    custom_field_name: str | None = None,
) -> str | None:
    bag = device.attribute_bags.get("nautobot")
    if not isinstance(bag, dict) or not bag:
        return None

    if custom_field_name is not None:
        custom_fields = bag.get("custom_fields")
        if not isinstance(custom_fields, dict):
            return None
        return _stringify_resolved(custom_fields.get(custom_field_name))

    if field_key not in bag:
        return None

    extracted = extract_update_fields_from_nautobot_bag({field_key: bag[field_key]})
    value = extracted.get(field_key)
    if value is None:
        return None
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if str(item).strip()) or None
    if isinstance(value, dict):
        return None
    return str(value).strip() or None


def _resolve_attribute_path(
    device: DeviceContext,
    path: str,
    *,
    run_id: str | None = None,
) -> str | None:
    resolved = resolve_device_attribute(device, path)
    if resolved is not None:
        return resolved
    return _stringify_resolved(resolve_device_value(device, path, run_id=run_id))


def resolve_update_field_expression(
    *,
    device: DeviceContext,
    field_key: str,
    raw_value: str,
    run_id: str | None = None,
    custom_field_name: str | None = None,
) -> str | None:
    """Resolve a field value expression for one device."""
    expression = raw_value.strip()
    if not expression:
        return None

    match = _BRACE_EXPRESSION.match(expression)
    if not match:
        return expression

    path = match.group("path").strip()
    default_value = match.group("default")

    if path == "nautobot.origin":
        resolved = _resolve_nautobot_origin(
            device,
            field_key,
            custom_field_name=custom_field_name,
        )
    else:
        resolved = _resolve_attribute_path(device, path, run_id=run_id)

    if resolved is not None:
        return resolved
    if default_value is not None:
        return default_value
    return None


def _parse_tags_value(raw: str) -> list[str] | str | None:
    cleaned = raw.strip()
    if not cleaned:
        return None
    if "," in cleaned or ";" in cleaned or "\n" in cleaned:
        tags = [
            item.strip()
            for part in cleaned.replace(";", ",").replace("\n", ",").split(",")
            for item in [part.strip()]
            if item
        ]
        return tags or None
    return cleaned


def build_resolved_update_data(
    *,
    device: DeviceContext,
    raw_fields: dict[str, Any],
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build the Nautobot update payload for one device from enabled field specs."""
    update_data: dict[str, Any] = {}

    for key in _DEVICE_FIELD_KEYS:
        if key == "custom_fields":
            continue
        enabled, value_expr = normalize_field_spec(raw_fields.get(key))
        if not enabled:
            continue

        resolved = resolve_update_field_expression(
            device=device,
            field_key=key,
            raw_value=value_expr,
            run_id=run_id,
        )
        if resolved is None:
            continue

        if key == "tags":
            parsed_tags = _parse_tags_value(resolved)
            if parsed_tags is not None:
                update_data[key] = parsed_tags
            continue

        update_data[key] = resolved

    raw_custom_fields = raw_fields.get("custom_fields")
    if isinstance(raw_custom_fields, dict):
        custom_fields: dict[str, str] = {}
        for cf_name, cf_raw in raw_custom_fields.items():
            name = str(cf_name).strip()
            if not name:
                continue
            enabled, value_expr = normalize_field_spec(cf_raw)
            if not enabled:
                continue
            resolved = resolve_update_field_expression(
                device=device,
                field_key="custom_fields",
                raw_value=value_expr,
                run_id=run_id,
                custom_field_name=name,
            )
            if resolved is not None:
                custom_fields[name] = resolved
        if custom_fields:
            update_data["custom_fields"] = custom_fields

    return update_data
