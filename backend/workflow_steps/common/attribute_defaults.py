"""Normalize and merge default values into a device's ``nautobot`` attribute bag.

Used by the ``set-default-attributes`` step to seed values that ``{nautobot.origin}``
(``workflow_steps/common/update_field_expression.py``) can later resolve, without ever
calling the live Nautobot API. Both configuration modes (manual panel, git YAML)
converge on the same flat ``{role, status, ..., custom_fields, interfaces}`` shape via
``normalize_defaults_block`` before being merged with ``merge_nautobot_defaults``.
"""

from __future__ import annotations

from typing import Any

_NAMED_REFERENCE_KEYS = ("role", "status", "location", "platform", "rack")
_SCALAR_KEYS = ("software_version", "serial", "asset_tag", "face", "position")


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _merge_interfaces(existing: Any, defaults: Any, *, overwrite: bool) -> list[Any]:
    existing_list = existing if isinstance(existing, list) else []
    if not isinstance(defaults, list):
        return existing_list

    by_name: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in existing_list:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or name in by_name:
            continue
        by_name[name] = dict(item)
        order.append(name)

    for item in defaults:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        if name in by_name:
            if overwrite:
                by_name[name] = dict(item)
            continue
        by_name[name] = dict(item)
        order.append(name)

    return [by_name[name] for name in order]


def _merge_custom_fields(existing: Any, defaults: Any, *, overwrite: bool) -> dict[str, Any]:
    merged = dict(existing) if isinstance(existing, dict) else {}
    if not isinstance(defaults, dict):
        return merged
    for key, value in defaults.items():
        if overwrite or _is_empty(merged.get(key)):
            merged[key] = value
    return merged


def merge_nautobot_defaults(
    existing: dict[str, Any] | None,
    defaults: dict[str, Any] | None,
    *,
    overwrite: bool,
) -> dict[str, Any]:
    """Recursively merge ``defaults`` into ``existing`` (a ``nautobot`` attribute bag).

    ``overwrite=False`` only fills in keys that are missing/``None``/empty on
    ``existing``; ``overwrite=True`` always applies the default. ``interfaces`` is
    matched by ``name`` (skip-or-replace-whole — never merged field-by-field within one
    interface); ``custom_fields`` is merged per key with the same overwrite/skip rule.
    Any other nested dict (e.g. ``device_type``) is merged key-by-key recursively, so a
    partial default (only ``manufacturer.name``, no ``model``) leaves the rest alone.
    """
    merged: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    if not defaults:
        return merged

    for key, default_value in defaults.items():
        if key == "interfaces":
            merged[key] = _merge_interfaces(merged.get(key), default_value, overwrite=overwrite)
            continue
        if key == "custom_fields":
            merged[key] = _merge_custom_fields(merged.get(key), default_value, overwrite=overwrite)
            continue

        current = merged.get(key)
        if isinstance(current, dict) and isinstance(default_value, dict):
            merged[key] = merge_nautobot_defaults(current, default_value, overwrite=overwrite)
            continue

        if overwrite or _is_empty(current):
            merged[key] = default_value

    return merged


def _named_reference_default(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        return {"name": name} if name else (value or None)
    text = str(value).strip() if value is not None else ""
    return {"name": text} if text else None


def _tags_default(value: Any) -> list[str] | None:
    if isinstance(value, list):
        tags = [str(item).strip() for item in value if str(item).strip()]
        return tags or None
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    tags = [part.strip() for part in text.replace(";", ",").split(",") if part.strip()]
    return tags or None


def _device_type_default(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    model = str(value.get("model") or "").strip()
    if model:
        result["model"] = model
    manufacturer = value.get("manufacturer")
    if isinstance(manufacturer, dict):
        name = str(manufacturer.get("name") or "").strip()
        if name:
            result["manufacturer"] = {"name": name}
    elif manufacturer is not None and str(manufacturer).strip():
        result["manufacturer"] = {"name": str(manufacturer).strip()}
    return result or None


def _interface_status_default(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        return {"name": name} if name else None
    text = str(value).strip() if value is not None else ""
    return {"name": text} if text else None


def _interface_ip_addresses_default(value: Any) -> list[dict[str, Any]]:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            address = str(item.get("address") or "").strip()
        else:
            address = str(item).strip()
        if address:
            result.append({"address": address})
    return result


def _normalize_interface_default(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    entry: dict[str, Any] = {"name": name}

    iface_type = str(raw.get("type") or "").strip()
    if iface_type:
        entry["type"] = iface_type

    description = str(raw.get("description") or "").strip()
    if description:
        entry["description"] = description

    status = _interface_status_default(raw.get("status"))
    if status:
        entry["status"] = status

    ip_addresses = _interface_ip_addresses_default(raw.get("ip_addresses"))
    if ip_addresses:
        entry["ip_addresses"] = ip_addresses

    return entry


def normalize_defaults_block(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a flat ``{role, status, ..., custom_fields, interfaces}`` mapping —
    from either a parsed git YAML ``devices:`` block or the manual config panel — into
    the nested shape expected in ``attribute_bags["nautobot"]``."""
    if not isinstance(raw, dict):
        return {}

    defaults: dict[str, Any] = {}

    for key in _NAMED_REFERENCE_KEYS:
        if key in raw:
            value = _named_reference_default(raw[key])
            if value:
                defaults[key] = value

    if "tags" in raw:
        tags = _tags_default(raw["tags"])
        if tags:
            defaults["tags"] = tags

    if "device_type" in raw:
        device_type = _device_type_default(raw["device_type"])
        if device_type:
            defaults["device_type"] = device_type

    for key in _SCALAR_KEYS:
        if key in raw and raw[key] is not None:
            text = str(raw[key]).strip()
            if text:
                defaults[key] = text

    custom_fields = raw.get("custom_fields")
    if isinstance(custom_fields, dict):
        cleaned = {
            str(name).strip(): str(field_value).strip()
            for name, field_value in custom_fields.items()
            if str(name).strip() and field_value is not None and str(field_value).strip()
        }
        if cleaned:
            defaults["custom_fields"] = cleaned

    interfaces = raw.get("interfaces")
    if isinstance(interfaces, list):
        normalized = [
            entry
            for item in interfaces
            if isinstance(item, dict) and (entry := _normalize_interface_default(item)) is not None
        ]
        if normalized:
            defaults["interfaces"] = normalized

    return defaults
