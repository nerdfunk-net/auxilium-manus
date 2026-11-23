"""``DeviceResolver`` picks the device a write goes to: strict like the step helper (P-N1, W2-01).

``common/nautobot_resolve`` (steps) raises ``NautobotAmbiguousMatchError`` for two devices of one
name or one primary IP, surfaces GraphQL/transport errors and never accepts a device with another
name. The service-side resolver (``DeviceCommonService``, used by ``DeviceUpdateService`` and the
Start Job UUID resolution) returned the first match and turned every failure into "not found",
so a write could go to the wrong device. The ``contains`` / ``starts_with`` strategies are
explicit "first match" lookups and stay as they are.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.nautobot.common.exceptions import NautobotAmbiguousMatchError, NautobotAPIError
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.devices.update import DeviceUpdateService
from services.nautobot.devices.uuid_resolver import resolve_nautobot_uuid
from services.nautobot.resolvers.device_resolver import DeviceResolver


def _resolver(result: Any = None, *, error: Exception | None = None) -> DeviceResolver:
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(return_value=result, side_effect=error)
    return DeviceResolver(nautobot)


def _devices(*items: dict[str, Any]) -> dict[str, Any]:
    return {"data": {"devices": list(items)}}


def _ips(*primary_for: Any) -> dict[str, Any]:
    return {
        "data": {
            "ip_addresses": [
                {"id": f"ip{i}", "primary_ip4_for": p} for i, p in enumerate(primary_for)
            ]
        }
    }


# --- by name -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_device_resolves_to_its_id() -> None:
    resolver = _resolver(_devices({"id": "u1", "name": "sw1"}))

    assert await resolver.resolve_device_by_name("sw1") == "u1"


@pytest.mark.asyncio
async def test_no_device_resolves_to_none() -> None:
    assert await _resolver(_devices()).resolve_device_by_name("sw1") is None


@pytest.mark.asyncio
async def test_two_devices_with_one_name_are_ambiguous() -> None:
    resolver = _resolver(_devices({"id": "u1", "name": "sw1"}, {"id": "u2", "name": "sw1"}))

    with pytest.raises(NautobotAmbiguousMatchError, match="2 Nautobot devices are named 'sw1'"):
        await resolver.resolve_device_by_name("sw1")


@pytest.mark.asyncio
async def test_the_same_device_listed_twice_is_not_ambiguous() -> None:
    resolver = _resolver(_devices({"id": "u1", "name": "sw1"}, {"id": "u1", "name": "sw1"}))

    assert await resolver.resolve_device_by_name("sw1") == "u1"


@pytest.mark.asyncio
async def test_a_device_with_another_name_is_never_taken() -> None:
    resolver = _resolver(_devices({"id": "u9", "name": "SW1-OLD"}))

    assert await resolver.resolve_device_by_name("sw1") is None


@pytest.mark.asyncio
async def test_a_graphql_error_is_raised_not_reported_as_not_found() -> None:
    resolver = _resolver({"errors": [{"message": "boom"}]})

    with pytest.raises(NautobotAPIError) as raised:
        await resolver.resolve_device_by_name("sw1")

    assert raised.value.code == "graphql_error"
    assert "boom" not in str(raised.value)


@pytest.mark.asyncio
async def test_a_transport_error_is_not_reported_as_not_found() -> None:
    resolver = _resolver(error=NautobotAPIError("timed out", code="timeout"))

    with pytest.raises(NautobotAPIError):
        await resolver.resolve_device_by_name("sw1")


# --- by primary IP -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_devices_with_one_primary_ip_are_ambiguous() -> None:
    resolver = _resolver(_ips([{"id": "u1", "name": "a"}], [{"id": "u2", "name": "b"}]))

    with pytest.raises(NautobotAmbiguousMatchError, match="primary IP 10.0.0.1"):
        await resolver.resolve_device_by_ip("10.0.0.1")


@pytest.mark.asyncio
async def test_one_primary_ip_device_resolves_in_list_and_dict_form() -> None:
    assert (
        await _resolver(_ips([{"id": "u1", "name": "a"}])).resolve_device_by_ip("10.0.0.1") == "u1"
    )
    assert await _resolver(_ips({"id": "u1", "name": "a"})).resolve_device_by_ip("10.0.0.1") == "u1"


@pytest.mark.asyncio
async def test_an_ip_error_is_raised_not_reported_as_not_found() -> None:
    with pytest.raises(NautobotAPIError):
        await _resolver({"errors": ["nope"]}).resolve_device_by_ip("10.0.0.1")


# --- the id / strategy front door --------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_device_id_surfaces_the_ambiguity_instead_of_trying_the_ip() -> None:
    resolver = _resolver(_devices({"id": "u1", "name": "sw1"}, {"id": "u2", "name": "sw1"}))

    with pytest.raises(NautobotAmbiguousMatchError):
        await resolver.resolve_device_id(device_name="sw1", ip_address="10.0.0.1")


@pytest.mark.asyncio
async def test_contains_strategy_keeps_its_documented_first_match() -> None:
    resolver = _resolver(_devices({"id": "u1", "name": "sw1-a"}, {"id": "u2", "name": "sw1-b"}))

    assert await resolver.resolve_device_id(device_name="sw1", matching_strategy="contains") == "u1"


# --- through the real services (W13-06 (1): not a patched resolver) -----------------------------


@pytest.mark.asyncio
async def test_the_update_service_refuses_to_pick_between_two_same_named_devices() -> None:
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(
        return_value=_devices({"id": "u1", "name": "sw1"}, {"id": "u2", "name": "sw1"})
    )
    nautobot.rest_request = AsyncMock()
    service = DeviceUpdateService(nautobot)

    with pytest.raises(NautobotAmbiguousMatchError):
        await service._resolve_device_id({"name": "sw1"})

    nautobot.rest_request.assert_not_called()  # nothing was read or written for either device


@pytest.mark.asyncio
async def test_the_uuid_resolver_reports_an_ambiguous_device_as_a_value_error() -> None:
    nautobot = MagicMock()
    nautobot.graphql_query = AsyncMock(
        return_value=_devices({"id": "u1", "name": "sw1"}, {"id": "u2", "name": "sw1"})
    )

    with pytest.raises(ValueError, match="could not resolve device 'sw1'"):
        await resolve_nautobot_uuid(DeviceCommonService(nautobot), "device", "sw1")
