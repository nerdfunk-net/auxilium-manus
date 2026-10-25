"""Map keys of a device file entry (YAML today, CSV later) to Nautobot attributes.

Pure functions, no I/O. A mapping is an ordered list of ``{source, target}`` rows where
``source`` is a key (or dot-path) of the raw file entry and ``target`` is a dot-path from
``NAUTOBOT_TARGETS``. The result of applying a mapping is a dict shaped like a Nautobot
device (``{"name": ..., "location": {"name": ...}}``), which the workflow stores in
``attribute_bags["nautobot"]``. Internal Nautobot UUIDs are never mappable.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
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
    "primary_ip4.parent.namespace.name",
    "role.name",
    "device_type.model",
    "device_type.manufacturer.name",
    "platform.name",
    "platform.network_driver",
    "location.name",
    "location.description",
    "location.parent.name",
    "status.name",
    "interfaces.name",
    "interfaces.description",
    "interfaces.type",
    "interfaces.mac_address",
    "interfaces.mtu",
    "interfaces.status.name",
    "interfaces.ip_addresses.address",
    "interfaces.ip_addresses.parent.namespace.name",
)

# Interface targets build one ``interfaces`` entry per file line (``apply_interface_mapping``).
INTERFACE_PREFIX = "interfaces."
INTERFACE_NAME_TARGET = "interfaces.name"
_INTERFACE_IP_TARGET = "interfaces.ip_addresses.address"
_INTERFACE_IP_NAMESPACE_TARGET = "interfaces.ip_addresses.parent.namespace.name"
_PRIMARY_IP_TARGET = "primary_ip4.address"
_PRIMARY_IP_NAMESPACE_TARGET = "primary_ip4.parent.namespace.name"

# Custom fields are open-ended: ``custom_fields.<name>`` for any simple name.
CUSTOM_FIELD_PREFIX = "custom_fields."
CUSTOM_FIELD_NAME = re.compile(r"[A-Za-z0-9_]+")
# A file key ``cf_<name>`` maps to ``custom_fields.<name>`` automatically.
CUSTOM_FIELD_KEY_PREFIX = "cf_"

# Custom values are not Nautobot data: ``custom.<name>`` for any simple name. They end up in the
# ``custom`` attribute bag of the device (see ``device_context_from_git_detail``).
CUSTOM_PREFIX = "custom."
CUSTOM_KEY = "custom"

# Targets that also populate real ``DeviceContext`` fields.
CORE_TARGETS: tuple[str, ...] = (
    "name",
    "primary_ip4.address",
    "platform.name",
    "platform.network_driver",
)

NAME_TARGET = "name"

# Pseudo target: the column/key is deliberately skipped. May be used for any number of columns.
IGNORE_TARGET = "_ignore"

# Pseudo target: the column flags the interface whose IP address becomes the device's primary IPv4
# address (``true``/``false``). It feeds no Nautobot field; the line's interface IP is copied to
# ``primary_ip4`` instead (``resolve_primary_ip``). At most one column.
PRIMARY_FLAG_TARGET = "_is_primary"
_PRIMARY_FLAG_TRUE = frozenset({"true", "t", "yes", "y", "1"})
_PRIMARY_FLAG_FALSE = frozenset({"false", "f", "no", "n", "0"})
PRIMARY_IP_PREFIX = "primary_ip4."
_PSEUDO_TARGETS = frozenset({IGNORE_TARGET, PRIMARY_FLAG_TARGET})

# Built-in mapping used when none is configured (the original hard-coded behaviour).
DEFAULT_DEVICE_MAPPING: tuple[MappingRule, ...] = (
    MappingRule("name", "name"),
    MappingRule("primary_ip4", "primary_ip4.address"),
    MappingRule("network_driver", "platform.network_driver"),
)


def is_custom_field_target(target: str) -> bool:
    return target.startswith(CUSTOM_FIELD_PREFIX) and bool(
        CUSTOM_FIELD_NAME.fullmatch(target[len(CUSTOM_FIELD_PREFIX) :])
    )


def is_custom_target(target: str) -> bool:
    return target.startswith(CUSTOM_PREFIX) and bool(
        CUSTOM_FIELD_NAME.fullmatch(target[len(CUSTOM_PREFIX) :])
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
        if target == IGNORE_TARGET:
            rules.append(MappingRule(source, target))
            continue
        if (
            target != PRIMARY_FLAG_TARGET
            and target not in NAUTOBOT_TARGETS
            and not is_custom_field_target(target)
            and not is_custom_target(target)
        ):
            raise ValueError(f"device_mapping row {index}: unknown target '{target}'")
        if target in seen_targets:
            raise ValueError(f"device_mapping row {index}: duplicate target '{target}'")
        seen_targets.add(target)
        rules.append(MappingRule(source, target))

    if NAME_TARGET not in seen_targets:
        raise ValueError("device_mapping must map a source key to the 'name' target")
    if INTERFACE_NAME_TARGET not in seen_targets and any(
        target.startswith(INTERFACE_PREFIX) for target in seen_targets
    ):
        # Without a name no interface is ever built, so its other attributes would be
        # dropped silently.
        raise ValueError(
            "device_mapping maps interface attributes but no source key "
            f"to '{INTERFACE_NAME_TARGET}'"
        )
    if PRIMARY_FLAG_TARGET in seen_targets:
        if _INTERFACE_IP_TARGET not in seen_targets:
            raise ValueError(
                f"device_mapping maps a primary flag but no source key to '{_INTERFACE_IP_TARGET}'"
            )
        clash = next((t for t in sorted(seen_targets) if t.startswith(PRIMARY_IP_PREFIX)), None)
        if clash is not None:
            # The flagged interface IP defines primary_ip4; a second source would be ambiguous.
            raise ValueError(f"device_mapping: the primary flag cannot be combined with '{clash}'")
    if _PRIMARY_IP_NAMESPACE_TARGET in seen_targets and _PRIMARY_IP_TARGET not in seen_targets:
        raise ValueError(
            "device_mapping maps a primary IPv4 namespace but no source key "
            f"to '{_PRIMARY_IP_TARGET}'"
        )
    if _INTERFACE_IP_NAMESPACE_TARGET in seen_targets and _INTERFACE_IP_TARGET not in seen_targets:
        # A namespace belongs to an address; alone it would be dropped silently.
        raise ValueError(
            "device_mapping maps an interface IP namespace but no source key "
            f"to '{_INTERFACE_IP_TARGET}'"
        )
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
        if rule.target.startswith(INTERFACE_PREFIX) or rule.target in _PSEUDO_TARGETS:
            continue
        value = _normalize_value(resolve_source_value(entry, rule.source), rule)
        if value is not None:
            result = _with_path(result, rule.target.split("."), value)
    if not result.get(NAME_TARGET):
        return None
    primary_ip = result.get("primary_ip4")
    if isinstance(primary_ip, dict) and not primary_ip.get("address"):
        # A namespace belongs to an address; without one it would leave an address-less object.
        return {k: v for k, v in result.items() if k != "primary_ip4"}
    return result


def apply_interface_mapping(entry: Any, rules: Iterable[MappingRule]) -> dict[str, Any] | None:
    """Build one Nautobot-shaped interface dict from a file line, or ``None``.

    Only ``interfaces.*`` targets are used; an interface needs a ``name``. The IP address is
    emitted as ``ip_addresses: [{"address": ...}]`` like the Nautobot attribute bag.
    """
    if not isinstance(entry, Mapping):
        return None
    result: dict[str, Any] = {}
    ip_address: str | None = None
    ip_namespace: str | None = None
    for rule in rules:
        if not rule.target.startswith(INTERFACE_PREFIX):
            continue
        value = _normalize_value(resolve_source_value(entry, rule.source), rule)
        if value is None:
            continue
        if rule.target == _INTERFACE_IP_TARGET:
            ip_address = value
        elif rule.target == _INTERFACE_IP_NAMESPACE_TARGET:
            ip_namespace = value
        else:
            result = _with_path(result, rule.target[len(INTERFACE_PREFIX) :].split("."), value)
    if not result.get("name"):
        return None
    if ip_address is not None:
        ip_entry: dict[str, Any] = {"address": ip_address}
        if ip_namespace is not None:
            ip_entry = {**ip_entry, "parent": {"namespace": {"name": ip_namespace}}}
        result = {**result, "ip_addresses": [ip_entry]}
    return result


class DeviceProblem(NamedTuple):
    """A data problem that fails one device (routed to the step's ``failure`` outcome)."""

    code: str
    message: str


@dataclass(frozen=True)
class PrimaryResolution:
    primary_ip4: dict[str, Any] | None
    problems: tuple[DeviceProblem, ...] = ()


def primary_flag_source(rules: Iterable[MappingRule]) -> str | None:
    return next((r.source for r in rules if r.target == PRIMARY_FLAG_TARGET), None)


def read_primary_flag(entry: Mapping[str, Any], rules: Iterable[MappingRule]) -> bool | None:
    """The primary flag of a file line: ``True``/``False``, or ``None`` for an unreadable value.

    Without a flag column, or with a blank cell, the line is not primary.
    """
    source = primary_flag_source(rules)
    if source is None:
        return False
    value = resolve_source_value(entry, source)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip().lower()
    if not text or text in _PRIMARY_FLAG_FALSE:
        return False
    return True if text in _PRIMARY_FLAG_TRUE else None


def _interface_address(interface: Mapping[str, Any]) -> tuple[str | None, Mapping[str, Any]]:
    ips = interface.get("ip_addresses")
    first = ips[0] if isinstance(ips, list) and ips and isinstance(ips[0], Mapping) else {}
    address = first.get("address")
    return (str(address) if address else None), first


_TEXT_LIMIT = 60
_LISTED_LIMIT = 5


def safe_text(value: object, limit: int = _TEXT_LIMIT) -> str:
    """File content for a message: one line, printable characters only, at most ``limit`` long.

    Messages end up in logs, persisted step output and the preview, so a cell must not be able
    to add a log line or carry a long value (a shifted column can hold a secret) into them.
    """
    text = "".join(ch if ch.isprintable() else " " for ch in str(value)).strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _ip_namespace(ip_entry: Mapping[str, Any]) -> str | None:
    parent = ip_entry.get("parent")
    namespace = parent.get("namespace") if isinstance(parent, Mapping) else None
    name = namespace.get("name") if isinstance(namespace, Mapping) else None
    return str(name) if name else None


def resolve_primary_ip(flagged_interfaces: Sequence[Mapping[str, Any]]) -> PrimaryResolution:
    """Pick the device's primary IPv4 from the interfaces whose line was flagged primary.

    Exactly one distinct (interface, address, namespace) gives ``primary_ip4`` (address plus
    namespace of that interface IP); none gives no primary IP; several, or a flagged line
    without an address, give a problem and no primary IP. The same address in two namespaces is
    two addresses in Nautobot, so it counts as two.
    """
    with_address: dict[tuple[str, str, str | None], Mapping[str, Any]] = {}
    without_address: list[str] = []
    for interface in flagged_interfaces:
        name = safe_text(interface.get("name") or "(unnamed interface)")
        address, ip_entry = _interface_address(interface)
        if address is None:
            without_address.append(name)
        else:
            key = (name, safe_text(address), _ip_namespace(ip_entry))
            with_address.setdefault(key, ip_entry)

    problems: list[DeviceProblem] = []
    if without_address:
        listed = ", ".join(without_address[:_LISTED_LIMIT])
        more = len(without_address) - _LISTED_LIMIT
        problems.append(
            DeviceProblem(
                "primary_without_address",
                "marked as primary but has no IP address: "
                + listed
                + (f" and {more} more" if more > 0 else ""),
            )
        )
    if len(with_address) > 1:
        entries = [
            f"{name} ({address}{f', namespace {ns}' if ns else ''})"
            for name, address, ns in with_address
        ]
        more = len(entries) - _LISTED_LIMIT
        problems.append(
            DeviceProblem(
                "multiple_primary_ip",
                f"{len(with_address)} interfaces are marked as primary, only one is allowed: "
                + ", ".join(entries[:_LISTED_LIMIT])
                + (f" and {more} more" if more > 0 else ""),
            )
        )
    if problems or not with_address:
        return PrimaryResolution(None, tuple(problems))
    ip_entry = next(iter(with_address.values()))
    address, _ = _interface_address({"ip_addresses": [ip_entry]})
    primary: dict[str, Any] = {"address": address}
    if isinstance(ip_entry.get("parent"), Mapping):
        primary = {**primary, "parent": ip_entry["parent"]}
    return PrimaryResolution(primary)


def with_implicit_custom_field_rules(
    rules: Sequence[MappingRule], keys: Iterable[str]
) -> list[MappingRule]:
    """Append ``cf_<name>`` -> ``custom_fields.<name>`` for file keys not mapped explicitly."""
    sources = {rule.source for rule in rules}
    targets = {rule.target for rule in rules}
    extra: list[MappingRule] = []
    for key in keys:
        if not key.startswith(CUSTOM_FIELD_KEY_PREFIX) or key in sources:
            continue
        name = key[len(CUSTOM_FIELD_KEY_PREFIX) :]
        target = f"{CUSTOM_FIELD_PREFIX}{name}"
        if CUSTOM_FIELD_NAME.fullmatch(name) and target not in targets:
            extra.append(MappingRule(key, target))
            targets.add(target)
    return [*rules, *extra]


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
