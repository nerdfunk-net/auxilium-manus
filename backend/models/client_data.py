"""Validated rows for the client data tables (written by the collect-client-data step)."""

from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator

CollectionStatus = Literal["ok", "not_supported", "no_template", "skipped"]

_MAC = re.compile(r"^[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}$")


def _fit(width: int) -> BeforeValidator:
    """Cut a string to its column width: one overlong value must not drop a whole collection."""

    def fit(value: Any) -> Any:
        return value[:width] if isinstance(value, str) else value

    return BeforeValidator(fit)


Vlan = Annotated[str | None, _fit(20)]
Interface = Annotated[str | None, _fit(255)]
Vrf = Annotated[str | None, _fit(64)]
Hostname = Annotated[str, _fit(255)]


def _check_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise ValueError(f"not an IP address: {value!r}") from exc


def _check_mac(value: str) -> str:
    if not _MAC.match(value):
        raise ValueError(f"not a dotted-quad MAC address: {value!r}")
    return value


class _Row(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ClientIpRow(_Row):
    ip_address: str
    mac_address: str | None = None
    interface: Interface = None
    vrf: Vrf = None
    vlan: Vlan = None

    @field_validator("ip_address")
    @classmethod
    def _ip(cls, value: str) -> str:
        return _check_ip(value)

    @field_validator("mac_address")
    @classmethod
    def _mac(cls, value: str | None) -> str | None:
        return None if value is None else _check_mac(value)


class ClientMacRow(_Row):
    mac_address: str
    vlan: Vlan = None
    port: Interface = None

    @field_validator("mac_address")
    @classmethod
    def _mac(cls, value: str) -> str:
        return _check_mac(value)


class ClientHostnameRow(_Row):
    ip_address: str
    hostname: Hostname

    @field_validator("ip_address")
    @classmethod
    def _ip(cls, value: str) -> str:
        return _check_ip(value)


class ClientCollectionStatus(_Row):
    """Outcome of each command of one device's collection."""

    arp_status: CollectionStatus = "skipped"
    mac_status: CollectionStatus = "skipped"
    vrf_status: CollectionStatus = "skipped"
    vrf_count: int = 0
