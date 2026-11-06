"""Device filters for Cisco ACI, shared by the workflow step, the preview API and Ask the Net.

Only the role is narrowed on the APIC (it is cheap and keeps the controllers out); everything else
is applied here, client-side, because a fabric is small and these semantics are then identical on
every APIC release:

- values of one filter are OR, different filters are AND;
- text filters are case-sensitive, whole-value matches;
- ``*`` (any text) and ``?`` (one character) are the only wildcards; every other character is
  literal, so regex syntax matches nothing special;
- the CIDR is checked against the management IP, and a device without one never matches.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from models.aci import AciDevice
from services.aci.common.exceptions import AciValidationError

MAX_VALUES_PER_FILTER = 50
_MAX_VALUE_CHARS = 255
ALLOWED_ROLES: tuple[str, ...] = ("leaf", "spine")

# config key (also the dataclass field) -> AciDevice attribute
_TEXT_FILTERS: dict[str, str] = {
    "names": "name",
    "models": "model",
    "serials": "serial_number",
    "versions": "software_version",
    "fabric_states": "fabric_state",
}
_INT_FILTERS: dict[str, str] = {"pod_ids": "pod_id", "node_ids": "node_id"}
_ROLES_KEY = "roles"
_CIDR_KEY = "cidr"
_KNOWN_KEYS = {*_TEXT_FILTERS, *_INT_FILTERS, _ROLES_KEY, _CIDR_KEY}


def _clean_text_values(key: str, raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)) or not all(isinstance(item, str) for item in raw):
        raise AciValidationError(f"Filter '{key}' must be a list of text values")
    seen: dict[str, None] = {}
    for item in raw:
        value = item.strip()
        if not value:
            continue
        if len(value) > _MAX_VALUE_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise AciValidationError(f"Filter '{key}' has an invalid value")
        seen.setdefault(value)
    if len(seen) > MAX_VALUES_PER_FILTER:
        raise AciValidationError(f"Filter '{key}' allows at most {MAX_VALUES_PER_FILTER} values")
    return tuple(seen)


def _clean_int_values(key: str, raw: Any) -> tuple[int, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise AciValidationError(f"Filter '{key}' must be a list of whole numbers")
    seen: dict[int, None] = {}
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise AciValidationError(f"Filter '{key}' must be a list of whole numbers")
        if isinstance(item, str) and not item.strip():
            continue  # a blank line of the step's textarea, like the text filters ignore
        try:
            number = int(item.strip()) if isinstance(item, str) else item
        except ValueError:
            raise AciValidationError(f"Filter '{key}' must be a list of whole numbers") from None
        if number < 1:
            raise AciValidationError(f"Filter '{key}' values must be 1 or higher")
        seen.setdefault(number)
    if len(seen) > MAX_VALUES_PER_FILTER:
        raise AciValidationError(f"Filter '{key}' allows at most {MAX_VALUES_PER_FILTER} values")
    return tuple(seen)


def _clean_roles(raw: Any) -> tuple[str, ...]:
    values = _clean_text_values(_ROLES_KEY, raw)
    unknown = [value for value in values if value not in ALLOWED_ROLES]
    if unknown:
        raise AciValidationError(f"Unsupported role '{unknown[0]}'; use leaf or spine")
    # Fixed order, so the same selection always produces the same APIC query.
    return tuple(role for role in ALLOWED_ROLES if role in values)


def _clean_cidr(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise AciValidationError("Filter 'cidr' must be text")
    value = raw.strip()
    if not value:
        return None
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise AciValidationError(f"Invalid CIDR '{value}'") from exc
    if network.version != 4:
        # Management addresses are IPv4 only, so an IPv6 network could never match a switch.
        raise AciValidationError("Filter 'cidr' must be an IPv4 network")
    return str(network)


def _wildcard_match(pattern: str, value: str | None) -> bool:
    """Whole-value match of ``value`` against ``pattern`` (``*`` = any text, ``?`` = one character).

    A linear scan with one backtrack point (the last ``*``), never a regular expression: the pattern
    is typed by a user and runs in the API process or a worker, where a backtracking regex on
    twenty ``*`` and a ``!`` stalls the whole process. Worst case is O(len(pattern) * len(value)),
    which the 255-character value cap keeps tiny.
    """
    if value is None:
        return False
    p = v = 0
    star = -1  # index of the last '*' in the pattern
    resume = 0  # where in the value the last '*' currently stops matching
    while v < len(value):
        if p < len(pattern) and pattern[p] == "*":
            star, resume = p, v
            p += 1
        elif p < len(pattern) and (pattern[p] == "?" or pattern[p] == value[v]):
            p += 1
            v += 1
        elif star != -1:
            p = star + 1
            resume += 1
            v = resume
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


@dataclass(frozen=True)
class AciDeviceFilters:
    names: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    pod_ids: tuple[int, ...] = ()
    node_ids: tuple[int, ...] = ()
    models: tuple[str, ...] = ()
    serials: tuple[str, ...] = ()
    versions: tuple[str, ...] = ()
    fabric_states: tuple[str, ...] = ()
    cidr: str | None = None

    @classmethod
    def from_config(cls, raw: Mapping[str, Any] | None) -> Self:
        """Validate a step-config / API ``filters`` object into immutable filters."""
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise AciValidationError("Filters must be an object")
        unknown = set(raw) - _KNOWN_KEYS
        if unknown:
            raise AciValidationError(f"Unknown filter: {sorted(unknown)[0]}")
        return cls(
            names=_clean_text_values("names", raw.get("names")),
            roles=_clean_roles(raw.get(_ROLES_KEY)),
            pod_ids=_clean_int_values("pod_ids", raw.get("pod_ids")),
            node_ids=_clean_int_values("node_ids", raw.get("node_ids")),
            models=_clean_text_values("models", raw.get("models")),
            serials=_clean_text_values("serials", raw.get("serials")),
            versions=_clean_text_values("versions", raw.get("versions")),
            fabric_states=_clean_text_values("fabric_states", raw.get("fabric_states")),
            cidr=_clean_cidr(raw.get(_CIDR_KEY)),
        )

    @property
    def is_empty(self) -> bool:
        keys = (*_TEXT_FILTERS, *_INT_FILTERS, _ROLES_KEY)
        return self.cidr is None and not any(getattr(self, key) for key in keys)

    def matches(self, device: AciDevice) -> bool:
        """True when ``device`` passes every filter that is set."""
        if self.roles and device.role not in self.roles:
            return False
        for key, attribute in _INT_FILTERS.items():
            allowed = getattr(self, key)
            if allowed and getattr(device, attribute) not in allowed:
                return False
        for key, attribute in _TEXT_FILTERS.items():
            patterns = getattr(self, key)
            if patterns and not any(
                _wildcard_match(pattern, getattr(device, attribute)) for pattern in patterns
            ):
                return False
        return self._matches_cidr(device.management_ip)

    def _matches_cidr(self, management_ip: str | None) -> bool:
        if self.cidr is None:
            return True
        try:
            return ipaddress.ip_address(management_ip or "") in ipaddress.ip_network(self.cidr)
        except ValueError:
            return False
