"""Device lookup by management address over the cached device list."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from models.sources_nautobot import DeviceInfo
from services.sources.nautobot.query_service import NautobotSourceQueryService


def _service(devices: list[DeviceInfo]) -> NautobotSourceQueryService:
    service = NautobotSourceQueryService.__new__(NautobotSourceQueryService)
    service._get_all_devices_cached = AsyncMock(return_value=devices)  # type: ignore[method-assign]
    return service


def _query(devices: list[DeviceInfo], ip: str) -> list[str]:
    service = _service(devices)
    return [d.id for d in asyncio.run(service._query_devices_by_primary_ip(ip))]


def test_the_mask_is_ignored_and_the_address_must_match_exactly() -> None:
    devices = [
        DeviceInfo(id="a", primary_ip4="10.0.0.5/24"),
        DeviceInfo(id="b", primary_ip4="10.0.0.50/24"),
        DeviceInfo(id="c", primary_ip4=None),
    ]
    assert _query(devices, "10.0.0.5") == ["a"]


def test_a_blank_address_matches_nothing() -> None:
    assert _query([DeviceInfo(id="c", primary_ip4=None)], " ") == []
