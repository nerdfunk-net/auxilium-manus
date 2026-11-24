"""P-C leftover: ``exists-in-nautobot`` (Exists in Nautobot) on the per-device runner.

One device that raises fails that device only. The text of a Nautobot client error is kept (the
client sanitises it); any other exception is reduced to its class name plus a ``FailureInfo``, so
driver text never reaches the stored run.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.nautobot.common.exceptions import NautobotAPIError
from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.exists_in_nautobot import executor as mod

_SECRET = "driver text with 10.9.9.9 and a token"
_UUID = "efce2684-f64d-4d27-9030-f0e71b1e45c0"


async def _run(query: Any, *names: str) -> dict[str, Any]:
    service = MagicMock()
    service.graphql_query = AsyncMock(side_effect=query)
    context = make_context([make_device(n) for n in names])
    with patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), service)):
        outcomes = await call_step(
            mod.execute,
            config={"nautobot_source_id": "src", "strategy": "name"},
            context=context,
            node_id="n1",
        )
    return {o.name: o.context for o in outcomes}


@pytest.mark.asyncio
async def test_unexpected_exception_hides_text_and_fails_only_that_device() -> None:
    async def query(_q: str, variables: dict[str, Any], _c: Any, **_kw: Any) -> dict[str, Any]:
        if variables["names"][0] == "A":
            raise RuntimeError(_SECRET)
        return {"data": {"devices": [{"id": _UUID, "name": "B"}]}}

    result = await _run(query, "A", "B")
    assert list(result["failure"].devices) == ["A"]
    assert list(result["exists"].devices) == ["B"]
    error = result["failure"].devices["A"].errors[-1]
    assert error.message == "RuntimeError"
    assert _SECRET not in str(result["failure"].devices["A"].errors)
    assert error.failure is not None
    assert error.failure.kind == "internal_error"
    assert error.step_id == "exists-in-nautobot"


@pytest.mark.asyncio
async def test_nautobot_client_text_is_kept() -> None:
    async def query(*_a: Any, **_kw: Any) -> dict[str, Any]:
        raise NautobotAPIError("Nautobot reported an error", code="graphql_error")

    result = await _run(query, "A")
    error = result["failure"].devices["A"].errors[-1]
    assert "Nautobot reported an error" in error.message
    assert error.failure is not None


@pytest.mark.asyncio
async def test_ip_unresolved_carries_the_code_and_counts_stay() -> None:
    service = MagicMock()
    service.graphql_query = AsyncMock()
    context = make_context([make_device("A", primary_ip4=None)])
    with patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), service)):
        outcomes = await call_step(
            mod.execute,
            config={
                "nautobot_source_id": "src",
                "strategy": "primary_ip",
                "ip_address": "{device.primary_ip4}",
            },
            context=context,
            node_id="n1",
        )
    by_name = {o.name: o.context for o in outcomes}
    assert by_name["failure"].devices["A"].errors[-1].code == "ip_unresolved"
    assert by_name["exists"].metadata["n1.exists_counts"] == {
        "exists": 0,
        "non_existing": 0,
        "failure": 1,
    }
