"""Canonical Pydantic models for workflow step output data types.

Each data type defined here matches the contract documented in doc/DATATYPES.md.
Add new types here as new step output types are introduced.
"""

from __future__ import annotations

from pydantic import BaseModel


class DeviceListGeneral(BaseModel):
    source_id: str
    total: int


class PrimaryIp4Detail(BaseModel):
    address: str


class PlatformDetail(BaseModel):
    name: str | None = None
    manufacturer: str | None = None
    network_driver: str | None = None


class DeviceDetail(BaseModel):
    id: str
    name: str
    serial: str | None = None
    location: str | None = None
    role: str | None = None
    tags: list[str] = []
    device_type: str | None = None
    manufacturer: str | None = None
    platform: PlatformDetail | None = None
    primary_ip4: PrimaryIp4Detail | None = None
    status: str | None = None


class DeviceList(BaseModel):
    """Canonical device_list type produced by inventory-selector steps."""

    general: DeviceListGeneral
    device_ids: list[str]
    device_details: list[DeviceDetail]
