"""Map workflow nautobot attribute bags to update-nautobot-device fields."""

from __future__ import annotations

from typing import Any

_NAMED_REFERENCE_FIELDS = frozenset({"location", "role", "status", "platform", "rack"})
_DEVICE_TYPE_FIELD = "device_type"


def _strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _named_reference_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("name", "id"):
            candidate = _strip_empty(value.get(key))
            if candidate is not None:
                return str(candidate)
        return None
    cleaned = _strip_empty(value)
    return str(cleaned) if cleaned is not None else None


def _device_type_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("model", "name", "id"):
            candidate = _strip_empty(value.get(key))
            if candidate is not None:
                return str(candidate)
        return None
    cleaned = _strip_empty(value)
    return str(cleaned) if cleaned is not None else None


def _primary_ip4_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("address", "host"):
            candidate = _strip_empty(value.get(key))
            if candidate is not None:
                return str(candidate)
        return None
    cleaned = _strip_empty(value)
    return str(cleaned) if cleaned is not None else None


def _tags_value(value: Any) -> list[str] | str | None:
    if isinstance(value, str):
        cleaned = _strip_empty(value)
        return cleaned
    if not isinstance(value, list):
        return None
    tags: list[str] = []
    for item in value:
        if isinstance(item, str):
            cleaned = _strip_empty(item)
            if cleaned:
                tags.append(str(cleaned))
            continue
        if isinstance(item, dict):
            cleaned = _named_reference_value(item)
            if cleaned:
                tags.append(cleaned)
    return tags or None


def _custom_fields_value(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict) or not value:
        return None
    cleaned = {
        str(key): str(item)
        for key, item in value.items()
        if str(key).strip() and item is not None and str(item).strip()
    }
    return cleaned or None


def _scalar_value(value: Any) -> str | None:
    cleaned = _strip_empty(value)
    return str(cleaned) if cleaned is not None else None


def extract_update_fields_from_nautobot_bag(bag: dict[str, Any]) -> dict[str, Any]:
    """Extract flat update-nautobot-device fields from a nautobot attribute bag."""
    if not isinstance(bag, dict) or not bag:
        return {}

    update_data: dict[str, Any] = {}

    for key in (
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
    ):
        if key not in bag:
            continue

        value = bag[key]
        if key in _NAMED_REFERENCE_FIELDS:
            normalized = _named_reference_value(value)
        elif key == _DEVICE_TYPE_FIELD:
            normalized = _device_type_value(value)
        elif key == "primary_ip4":
            normalized = _primary_ip4_value(value)
        elif key == "tags":
            normalized = _tags_value(value)
        elif key == "custom_fields":
            normalized = _custom_fields_value(value)
        else:
            normalized = _scalar_value(value)

        if normalized is not None:
            update_data[key] = normalized

    return update_data


def merge_update_data(
    config_fields: dict[str, Any],
    bag_fields: dict[str, Any],
) -> dict[str, Any]:
    """Merge config and bag fields; bag values override config for the same key."""
    merged = dict(config_fields)
    merged.update(bag_fields)
    return merged
