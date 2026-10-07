"""Map keys of a device file entry (YAML today, CSV later) to Nautobot attributes.

Pure functions, no I/O. A mapping is an ordered list of ``{source, target}`` rows where
``source`` is a key (or dot-path) of the raw file entry and ``target`` is a dot-path from
``NAUTOBOT_TARGETS``. The result of applying a mapping is a dict shaped like a Nautobot
device (``{"name": ..., "location": {"name": ...}}``), which the workflow stores in
``attribute_bags["nautobot"]``. Internal Nautobot UUIDs are never mappable.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)


class MappingRule(NamedTuple):
    source: str
    target: str


# Selectable Nautobot attributes (keep in sync with the frontend
# ``get-git-devices/constants/nautobot-targets.ts``).
NAUTOBOT_TARGETS: tuple[str, ...] = (
    "name",
    "hostname",
    "serial",
    "asset_tag",
    "position",
    "face",
    "primary_ip4.address",
    "primary_ip4.description",
    "primary_ip4.dns_name",
    "primary_ip4.status.name",
    "role.name",
    "device_type.model",
    "device_type.manufacturer.name",
    "platform.name",
    "platform.network_driver",
    "location.name",
    "location.description",
    "location.parent.name",
    "status.name",
)

# Targets that also populate real ``DeviceContext`` fields.
CORE_TARGETS: tuple[str, ...] = (
    "name",
    "primary_ip4.address",
    "platform.name",
    "platform.network_driver",
)

NAME_TARGET = "name"

# Built-in mapping used when none is configured (the original hard-coded behaviour).
DEFAULT_DEVICE_MAPPING: tuple[MappingRule, ...] = (
    MappingRule("name", "name"),
    MappingRule("primary_ip4", "primary_ip4.address"),
    MappingRule("network_driver", "platform.network_driver"),
)


def validate_device_mapping(raw: Any) -> list[MappingRule]:
    """Validate a configured mapping; an empty/unset mapping yields the default one."""
    if not raw:
        return list(DEFAULT_DEVICE_MAPPING)
    if not isinstance(raw, list):
        raise ValueError("device_mapping must be a list of {source, target} rows")

    rules: list[MappingRule] = []
    seen_targets: set[str] = set()
    for index, row in enumerate(raw, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"device_mapping row {index} must be an object")
        source = str(row.get("source") or "").strip()
        target = str(row.get("target") or "").strip()
        if not source:
            raise ValueError(f"device_mapping row {index}: source is empty")
        if target not in NAUTOBOT_TARGETS:
            raise ValueError(f"device_mapping row {index}: unknown target '{target}'")
        if target in seen_targets:
            raise ValueError(f"device_mapping row {index}: duplicate target '{target}'")
        seen_targets.add(target)
        rules.append(MappingRule(source, target))

    if NAME_TARGET not in seen_targets:
        raise ValueError("device_mapping must map a source key to the 'name' target")
    return rules


def resolve_source_value(entry: Mapping[str, Any], key: str) -> Any:
    """Look up ``key`` in ``entry``: a literal key first, then a dot-path."""
    if key in entry:
        return entry[key]
    current: Any = entry
    for part in key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _normalize_value(value: Any, rule: MappingRule) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list, tuple, set)):
        logger.warning(
            "device_mapping: source '%s' is not a scalar value; ignoring target '%s'",
            rule.source,
            rule.target,
        )
        return None
    text = str(value).strip()
    return text or None


def _with_path(tree: dict[str, Any], parts: Sequence[str], value: str) -> dict[str, Any]:
    """Return a copy of ``tree`` with ``value`` set at the nested ``parts`` path."""
    head, rest = parts[0], parts[1:]
    if not rest:
        return {**tree, head: value}
    child = tree.get(head)
    return {**tree, head: _with_path(child if isinstance(child, dict) else {}, rest, value)}


def apply_device_mapping(entry: Any, rules: Iterable[MappingRule]) -> dict[str, Any] | None:
    """Build a Nautobot-shaped dict from a raw file entry.

    Returns ``None`` when the entry is not a mapping or ``name`` resolves to nothing.
    """
    if not isinstance(entry, Mapping):
        return None
    result: dict[str, Any] = {}
    for rule in rules:
        value = _normalize_value(resolve_source_value(entry, rule.source), rule)
        if value is not None:
            result = _with_path(result, rule.target.split("."), value)
    if not result.get(NAME_TARGET):
        return None
    return result


def collect_available_keys(entries: Iterable[Mapping[str, Any]]) -> list[str]:
    """Sorted union of every key and dot-path (nested dicts) seen in ``entries``."""
    keys: set[str] = set()

    def walk(node: Mapping[str, Any], prefix: str) -> None:
        for key, value in node.items():
            path = f"{prefix}{key}"
            keys.add(path)
            if isinstance(value, Mapping):
                walk(value, f"{path}.")

    for entry in entries:
        if isinstance(entry, Mapping):
            walk(entry, "")
    return sorted(keys)
