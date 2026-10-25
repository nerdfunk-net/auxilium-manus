"""Column mapping for the device files: which CSV column feeds which attribute.

A reduced port of the app's ``services/git/device_mapping.py`` and ``device_grouping.py``: the
same ``{source, target}`` rows and the same interface / primary-flag rules, limited to what an
IP address lookup needs. Pure functions, no I/O. The result is Nautobot-shaped, so the app can
write it into an attribute bag unchanged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

NAME_TARGET = "name"
IGNORE_TARGET = "_ignore"
PRIMARY_FLAG_TARGET = "_is_primary"
INTERFACE_PREFIX = "interfaces."
INTERFACE_NAME_TARGET = "interfaces.name"
INTERFACE_IP_TARGET = "interfaces.ip_addresses.address"
INTERFACE_IP_NAMESPACE_TARGET = "interfaces.ip_addresses.parent.namespace.name"

TARGETS: tuple[str, ...] = (
    NAME_TARGET,
    INTERFACE_NAME_TARGET,
    "interfaces.description",
    "interfaces.type",
    "interfaces.mac_address",
    "interfaces.mtu",
    "interfaces.status.name",
    INTERFACE_IP_TARGET,
    INTERFACE_IP_NAMESPACE_TARGET,
)
_PSEUDO_TARGETS = frozenset({IGNORE_TARGET, PRIMARY_FLAG_TARGET})
_FLAG_TRUE = frozenset({"true", "t", "yes", "y", "1"})
_FLAG_FALSE = frozenset({"false", "f", "no", "n", "0"})
_TEXT_LIMIT = 60
_LISTED_LIMIT = 5


class MappingRule(NamedTuple):
    source: str
    target: str


class DeviceProblem(NamedTuple):
    """A data problem with one device (reported next to its data, never raised)."""

    code: str
    message: str


def safe_text(value: object, limit: int = _TEXT_LIMIT) -> str:
    """File content for a message: one line, printable characters only, at most ``limit`` long."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(value)).strip()
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def validate_mapping(raw: Any) -> list[MappingRule]:
    """Validate the configured rows; raises ``ValueError`` naming the first problem."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("mapping must be a list of {source, target} rows")
    rules: list[MappingRule] = []
    seen: set[str] = set()
    for index, row in enumerate(raw, start=1):
        if not isinstance(row, Mapping):
            raise ValueError(f"mapping row {index} must be an object")
        extra = sorted(set(row) - {"source", "target"})
        if extra:
            raise ValueError(f"mapping row {index}: unknown key {extra[0]!r}")
        source = str(row.get("source") or "").strip()
        target = str(row.get("target") or "").strip()
        if not source:
            raise ValueError(f"mapping row {index}: source is empty")
        if target == IGNORE_TARGET:
            rules.append(MappingRule(source, target))
            continue
        if target not in TARGETS and target != PRIMARY_FLAG_TARGET:
            raise ValueError(f"mapping row {index}: unknown target '{target}'")
        if target in seen:
            raise ValueError(f"mapping row {index}: duplicate target '{target}'")
        seen.add(target)
        rules.append(MappingRule(source, target))

    if NAME_TARGET not in seen:
        raise ValueError("mapping must map a column to the 'name' target")
    if INTERFACE_NAME_TARGET not in seen:
        raise ValueError(f"mapping must map a column to '{INTERFACE_NAME_TARGET}'")
    if PRIMARY_FLAG_TARGET in seen and INTERFACE_IP_TARGET not in seen:
        raise ValueError(f"mapping maps a primary flag but no column to '{INTERFACE_IP_TARGET}'")
    if INTERFACE_IP_NAMESPACE_TARGET in seen and INTERFACE_IP_TARGET not in seen:
        raise ValueError(f"mapping maps a namespace but no column to '{INTERFACE_IP_TARGET}'")
    return rules


def _text(entry: Mapping[str, Any], source: str) -> str | None:
    value = entry.get(source)
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    return str(value).strip() or None


def device_name(entry: Mapping[str, Any], rules: Sequence[MappingRule]) -> str | None:
    source = next(rule.source for rule in rules if rule.target == NAME_TARGET)
    return _text(entry, source)


def _with_path(tree: dict[str, Any], parts: Sequence[str], value: str) -> dict[str, Any]:
    head, rest = parts[0], parts[1:]
    if not rest:
        return {**tree, head: value}
    child = tree.get(head)
    return {**tree, head: _with_path(child if isinstance(child, dict) else {}, rest, value)}


def map_interface(entry: Mapping[str, Any], rules: Sequence[MappingRule]) -> dict[str, Any] | None:
    """One Nautobot-shaped interface from a file line, or ``None`` (an interface needs a name).

    The IP address is emitted as ``ip_addresses: [{"address": ..., "parent": {...}}]``.
    """
    result: dict[str, Any] = {}
    address: str | None = None
    namespace: str | None = None
    for rule in rules:
        if not rule.target.startswith(INTERFACE_PREFIX):
            continue
        value = _text(entry, rule.source)
        if value is None:
            continue
        if rule.target == INTERFACE_IP_TARGET:
            address = value
        elif rule.target == INTERFACE_IP_NAMESPACE_TARGET:
            namespace = value
        else:
            result = _with_path(result, rule.target[len(INTERFACE_PREFIX) :].split("."), value)
    if not result.get("name"):
        return None
    if address is not None:
        ip_entry: dict[str, Any] = {"address": address}
        if namespace is not None:
            ip_entry = {**ip_entry, "parent": {"namespace": {"name": namespace}}}
        result = {**result, "ip_addresses": [ip_entry]}
    return result


def read_primary_flag(entry: Mapping[str, Any], rules: Sequence[MappingRule]) -> bool | None:
    """``True``/``False`` for the flag of a line, ``None`` for an unreadable value.

    Without a flag column, or with a blank cell, the line is not primary.
    """
    source = next((r.source for r in rules if r.target == PRIMARY_FLAG_TARGET), None)
    if source is None:
        return False
    text = (_text(entry, source) or "").lower()
    if not text or text in _FLAG_FALSE:
        return False
    return True if text in _FLAG_TRUE else None


def flag_problem(rules: Sequence[MappingRule]) -> DeviceProblem:
    source = next(r.source for r in rules if r.target == PRIMARY_FLAG_TARGET)
    # The cell is deliberately not quoted: a shifted column can hold anything.
    return DeviceProblem(
        "invalid_primary_flag", f"column '{safe_text(source)}' is neither true nor false"
    )


@dataclass(frozen=True)
class PrimaryResolution:
    primary_ip4: dict[str, Any] | None
    problems: tuple[DeviceProblem, ...] = ()


def _first_ip(interface: Mapping[str, Any]) -> Mapping[str, Any]:
    ips = interface.get("ip_addresses")
    return ips[0] if isinstance(ips, list) and ips and isinstance(ips[0], Mapping) else {}


def _namespace(ip_entry: Mapping[str, Any]) -> str | None:
    parent = ip_entry.get("parent")
    namespace = parent.get("namespace") if isinstance(parent, Mapping) else None
    name = namespace.get("name") if isinstance(namespace, Mapping) else None
    return str(name) if name else None


def resolve_primary_ip(flagged: Sequence[Mapping[str, Any]]) -> PrimaryResolution:
    """Pick the primary IPv4 from the interfaces whose line was flagged primary.

    Exactly one distinct (interface, address, namespace) gives ``primary_ip4``; none gives no
    primary; several, or a flagged line without an address, give a problem and no primary. The
    same address in two namespaces is two addresses, as in Nautobot.
    """
    with_address: dict[tuple[str, str, str | None], Mapping[str, Any]] = {}
    without_address: list[str] = []
    for interface in flagged:
        name = safe_text(interface.get("name") or "(unnamed interface)")
        ip_entry = _first_ip(interface)
        address = ip_entry.get("address")
        if not address:
            without_address.append(name)
        else:
            with_address.setdefault((name, safe_text(address), _namespace(ip_entry)), ip_entry)

    problems: list[DeviceProblem] = []
    if without_address:
        more = len(without_address) - _LISTED_LIMIT
        problems.append(
            DeviceProblem(
                "primary_without_address",
                "marked as primary but has no IP address: "
                + ", ".join(without_address[:_LISTED_LIMIT])
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
    primary: dict[str, Any] = {"address": ip_entry["address"]}
    if isinstance(ip_entry.get("parent"), Mapping):
        primary = {**primary, "parent": ip_entry["parent"]}
    return PrimaryResolution(primary)
