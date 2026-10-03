"""Device-list filters for Cisco Catalyst Center, shared by the workflow step and the preview API.

Server semantics (verified live against the DevNet sandbox, see doc/CATALYST_CENTER_API_DIFF.md):
- every filter is a case-sensitive, full-string match;
- ``.*`` is the **only** wildcard (``.``, ``|``, ``[..]``, ``^$`` are literal / unsupported);
- a repeated query parameter means OR, different filters combine with AND;
- there is no CIDR filter, so a CIDR is a server-side prefix prefilter plus a client-side check.

Values are therefore passed to the server untouched; nothing here translates regex syntax.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Self

from services.catalyst_center.common.exceptions import CatalystCenterValidationError

MAX_VALUES_PER_FILTER = 50
_MAX_VALUE_CHARS = 255

# config key (also the dataclass field) -> Intent API query parameter
_LIST_FILTERS: dict[str, str] = {
    "hostnames": "hostname",
    "management_ips": "managementIpAddress",
    "families": "family",
    "roles": "role",
    "software_types": "softwareType",
    "software_versions": "softwareVersion",
    "platform_ids": "platformId",
    "serial_numbers": "serialNumber",
    "series": "series",
    "device_types": "type",
    "reachability_statuses": "reachabilityStatus",
    "collection_statuses": "collectionStatus",
}
_CIDR_KEY = "cidr"
_IP_PARAM = "managementIpAddress"


def _clean_values(key: str, raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)) or not all(isinstance(item, str) for item in raw):
        raise CatalystCenterValidationError(f"Filter '{key}' must be a list of text values")
    seen: dict[str, None] = {}
    for item in raw:
        value = item.strip()
        if not value:
            continue
        if len(value) > _MAX_VALUE_CHARS or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise CatalystCenterValidationError(f"Filter '{key}' has an invalid value")
        seen.setdefault(value)
    if len(seen) > MAX_VALUES_PER_FILTER:
        raise CatalystCenterValidationError(
            f"Filter '{key}' allows at most {MAX_VALUES_PER_FILTER} values"
        )
    return tuple(seen)


def _clean_cidr(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise CatalystCenterValidationError("Filter 'cidr' must be text")
    text = raw.strip()
    if not text:
        return None
    try:
        return str(ipaddress.ip_network(text, strict=False))
    except ValueError as exc:
        raise CatalystCenterValidationError(f"Invalid CIDR '{text}'") from exc


@dataclass(frozen=True)
class CatalystCenterDeviceFilters:
    hostnames: tuple[str, ...] = ()
    management_ips: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    software_types: tuple[str, ...] = ()
    software_versions: tuple[str, ...] = ()
    platform_ids: tuple[str, ...] = ()
    serial_numbers: tuple[str, ...] = ()
    series: tuple[str, ...] = ()
    device_types: tuple[str, ...] = ()
    reachability_statuses: tuple[str, ...] = ()
    collection_statuses: tuple[str, ...] = ()
    cidr: str | None = None

    @classmethod
    def from_config(cls, raw: Mapping[str, Any] | None) -> Self:
        """Validate a step-config / API ``filters`` object into immutable filters."""
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise CatalystCenterValidationError("Filters must be an object")
        unknown = set(raw) - set(_LIST_FILTERS) - {_CIDR_KEY}
        if unknown:
            raise CatalystCenterValidationError(f"Unknown filter: {sorted(unknown)[0]}")
        values = {key: _clean_values(key, raw.get(key)) for key in _LIST_FILTERS}
        return cls(**values, cidr=_clean_cidr(raw.get(_CIDR_KEY)))

    @property
    def is_empty(self) -> bool:
        return self.cidr is None and not any(getattr(self, key) for key in _LIST_FILTERS)

    def to_query_params(self) -> dict[str, list[str]]:
        """Intent API query parameters (each a list: repeated parameter = OR)."""
        params = {
            param: list(getattr(self, key))
            for key, param in _LIST_FILTERS.items()
            if getattr(self, key)
        }
        prefilter = self.cidr_prefilter()
        # Explicit management IPs already constrain the server query; the CIDR is then
        # applied client-side only, which keeps the two as an AND.
        if prefilter is not None and _IP_PARAM not in params:
            params[_IP_PARAM] = [prefilter]
        return params

    def cidr_prefilter(self) -> str | None:
        """Server-side wildcard for the whole octets shared by the CIDR's first/last address.

        ``10.10.20.0/24`` -> ``10.10.20..*``; a /32 -> the exact address; ``None`` when no
        whole octet is shared (or IPv6), in which case the CIDR is checked client-side only.
        """
        if self.cidr is None:
            return None
        network = ipaddress.ip_network(self.cidr)
        if network.version != 4:
            return None
        first = network.network_address.packed
        last = network.broadcast_address.packed
        shared = 0
        while shared < 4 and first[shared] == last[shared]:
            shared += 1
        if shared == 0:
            return None
        if shared == 4:
            return str(network.network_address)
        return ".".join(str(octet) for octet in first[:shared]) + "." + ".*"

    def matches_ip(self, management_ip: str | None) -> bool:
        """Client-side exact CIDR check (always true when no CIDR is set)."""
        if self.cidr is None:
            return True
        try:
            return ipaddress.ip_address((management_ip or "").strip()) in ipaddress.ip_network(
                self.cidr
            )
        except ValueError:
            return False
