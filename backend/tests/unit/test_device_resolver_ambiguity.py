"""``DeviceResolver.resolve_device_by_name`` with two devices of the same name (P-N1, W2-01).

The step helper ``common/nautobot_resolve`` raises ``NautobotAmbiguousMatchError`` for it; this
service-side resolver (used by the Nautobot steps through ``DeviceCommonService``, by
``DeviceUpdateService`` and by the Ask the Net tools) returns the first match, so a write can go
to the wrong device. Strictness is added here (P-N1); the other cases must not change.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.nautobot.common.exceptions import NautobotAmbiguousMatchError
from services.nautobot.resolvers.device_resolver import DeviceResolver
from tests.unit._step_helpers import strict_xfail


def _resolver(devices: list[dict[str, Any]] | None = None, *, errors: Any = None) -> DeviceResolver:
    nautobot = MagicMock()
    result: dict[str, Any] = {"data": {"devices": devices or []}}
    if errors is not None:
        result = {"errors": errors}
    nautobot.graphql_query = AsyncMock(return_value=result)
    return DeviceResolver(nautobot)


@pytest.mark.asyncio
async def test_one_device_resolves_to_its_id() -> None:
    assert await _resolver([{"id": "u1", "name": "sw1"}]).resolve_device_by_name("sw1") == "u1"


@pytest.mark.asyncio
async def test_no_device_resolves_to_none() -> None:
    assert await _resolver([]).resolve_device_by_name("sw1") is None


@pytest.mark.asyncio
async def test_a_graphql_error_resolves_to_none_today() -> None:
    assert await _resolver(errors=[{"message": "boom"}]).resolve_device_by_name("sw1") is None


@strict_xfail("W2-01", "the first of several same-named devices is returned")
@pytest.mark.asyncio
async def test_two_devices_with_one_name_are_ambiguous() -> None:
    resolver = _resolver([{"id": "u1", "name": "sw1"}, {"id": "u2", "name": "sw1"}])

    with pytest.raises(NautobotAmbiguousMatchError):
        await resolver.resolve_device_by_name("sw1")
