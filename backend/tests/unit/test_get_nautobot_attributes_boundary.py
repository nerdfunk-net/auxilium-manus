"""W6-06: `get-nautobot-attributes` (Get Nautobot Attributes) reads the detail query strictly and
never asks Nautobot for all devices at once.

A permission or schema error answers ``errors`` plus ``data.device = null``; read leniently it
became ``not_found`` with a fixed text and no cause. And 500 devices sent 1000 queries together.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.nautobot.common.exceptions import NautobotAPIError
from tests.unit._step_helpers import call_step, make_context, make_device, make_run
from workflow_steps.get_nautobot_attributes import executor as mod

_CONFIG = {"nautobot_source_id": "s"}


def _service(graphql: Any) -> MagicMock:
    service = MagicMock()
    service.graphql_query = graphql
    return service


async def _run(service: MagicMock, *names: str):
    context = make_context([make_device(name) for name in names])
    with (
        patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), service)),
        patch.object(mod, "device_query_for_groups", AsyncMock(return_value="query")),
        patch.object(
            mod,
            "resolve_nautobot_device_id",
            AsyncMock(side_effect=lambda **kw: "nb-" + kw["device"].id),
        ),
    ):
        outcomes = await call_step(mod.execute, _CONFIG, context, run=make_run())
    return {outcome.name: outcome.context for outcome in outcomes}


@pytest.mark.asyncio
async def test_a_graphql_error_answer_fails_the_device_with_its_cause() -> None:
    async def graphql(query, variables, credentials, *, strict=False):
        response = {"errors": [{"message": "permission denied"}], "data": {"device": None}}
        if strict:
            raise NautobotAPIError("GraphQL returned errors")
        return response

    out = await _run(_service(graphql), "d1")
    error = out["failure"].devices["d1"].errors[-1]
    assert error.code == "nautobotapierror"
    assert error.failure is not None


@pytest.mark.asyncio
async def test_devices_are_fetched_at_most_five_at_a_time() -> None:
    running = peak = 0

    async def graphql(query, variables, credentials, *, strict=False):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return {"data": {"device": {"id": variables["deviceId"], "name": "x"}}}

    out = await _run(_service(graphql), *[f"d{i}" for i in range(12)])
    assert len(out["success"].devices) == 12
    assert 1 < peak <= 5
