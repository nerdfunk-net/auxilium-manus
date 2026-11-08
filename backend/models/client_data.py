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


class TooManyRowsError(Exception):
    """One device's table has more rows than ``CLIENT_DATA_MAX_ROWS_PER_TABLE`` allows."""

    def __init__(self, table: str, limit: int) -> None:
        super().__init__(f"{table} table above the row cap of {limit}")
        self.table = table
        self.limit = limit


def check_row_cap(ip_count: int, mac_count: int, limit: int) -> None:
    """Raise ``TooManyRowsError`` when either table is above *limit* (equal is allowed)."""
    if ip_count > limit:
        raise TooManyRowsError("ARP", limit)
    if mac_count > limit:
        raise TooManyRowsError("MAC", limit)


class CollectionConflictError(Exception):
    """Another writer stored a collection for the same run and device name first.

    Devices are stored per name; two fan-out children that hold devices with one name are
    separate executions, so only the database unique key can tell. Not retried as a replace.
    """

    def __init__(self) -> None:
        super().__init__("a collection for this run and device name already exists")


class VrfResult(_Row):
    """What reading the ARP table of one discovered VRF gave.

    ``ok`` with ``rows == 0`` is an empty VRF; ``not_supported`` / ``no_template`` mean the device
    refused or the output was not a table; ``skipped`` means the VRF was found but not read.
    """

    name: Annotated[str, _fit(64)]
    status: CollectionStatus
    rows: int = 0


class ClientCollectionStatus(_Row):
    """Outcome of each command of one device's collection."""

    arp_status: CollectionStatus = "skipped"
    mac_status: CollectionStatus = "skipped"
    vrf_status: CollectionStatus = "skipped"
    vrf_count: int = 0
    # None = VRF discovery did not give a list (switched off, refused): unknown, not "no VRFs".
    vrfs: list[VrfResult] | None = None
