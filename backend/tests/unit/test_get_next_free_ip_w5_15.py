"""W5-15: get-next-free-ip (Get Next Free IP) reads prefixes through the shared Nautobot layer.

The strict prefix lookup and the ``available-ips`` read are ``NetworkResolver`` methods behind
``DeviceCommonService``; the step only maps their errors to its failure codes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import workflow_steps.get_next_free_ip.lookup as lookup
from services.nautobot.devices.common import DeviceCommonService

pytestmark = pytest.mark.asyncio


def test_the_step_keeps_no_rest_reads_of_its_own() -> None:
    assert not hasattr(lookup, "resolve_prefix_id")
    assert not hasattr(lookup, "fetch_available_ips")


async def test_the_facade_delegates_both_reads() -> None:
    common = DeviceCommonService(MagicMock())
    resolver = MagicMock()
    resolver.resolve_prefix = AsyncMock(return_value="p-id")
    resolver.available_ips = AsyncMock(return_value=[{"address": "10.0.0.5/24"}])
    common._network_resolver = resolver

    assert await common.resolve_prefix_id("10.0.0.0/24", "ns") == "p-id"
    assert await common.available_ips("p-id", limit=3) == [{"address": "10.0.0.5/24"}]
    resolver.resolve_prefix.assert_awaited_once_with("10.0.0.0/24", "ns")
    resolver.available_ips.assert_awaited_once_with("p-id", limit=3)
