"""W6-16: `get-ise-devices` (Get from ISE) checks its mode keys before any I/O, and a Nautobot
failure while expanding a subnet entry fails the step instead of keeping the raw subnet entry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.sources.nautobot.evaluator import InventoryEvaluationError
from tests.unit._step_helpers import call_step, make_context, make_run
from workflow_steps.get_ise_devices import executor as mod

_MOD = "workflow_steps.get_ise_devices.executor"
_BASE = {"ise_source_id": "ise"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "needle"),
    [
        ({"query_mode": "name"}, "device_names"),
        ({"query_mode": "name", "device_names": "r1"}, "device_names"),
        ({"query_mode": "name", "device_names": ["r1", 5]}, "device_names"),
        ({"query_mode": "group", "group_name": "  "}, "group_name"),
        ({"query_mode": "cidr"}, "cidr"),
        ({"query_mode": "cidr", "cidr": "not-a-network"}, "invalid cidr"),
    ],
)
async def test_a_bad_mode_key_fails_before_any_credential_or_service_lookup(
    config: dict[str, object], needle: str
) -> None:
    with (
        patch(f"{_MOD}.object_session") as session,
        patch(f"{_MOD}._build_ise_services") as build,
    ):
        with pytest.raises(ValueError, match=needle):
            await call_step(mod.execute, {**_BASE, **config}, make_context(), run=make_run())
    session.assert_not_called()
    build.assert_not_called()


@pytest.mark.asyncio
async def test_a_nautobot_failure_during_subnet_expansion_fails_the_step() -> None:
    device_service = MagicMock()
    device_service.get_device_by_name = AsyncMock(
        return_value={
            "NetworkDevice": {
                "id": "id-1",
                "name": "subnet-group",
                "NetworkDeviceIPList": [{"ipaddress": "10.0.0.5", "mask": 24}],
            }
        }
    )
    nautobot = MagicMock()
    nautobot.preview_inventory = AsyncMock(side_effect=InventoryEvaluationError("condition failed"))
    config = {
        **_BASE,
        "query_mode": "name",
        "device_names": ["subnet-group"],
        "resolve_to_devices": True,
        "nautobot_source_id": "nb",
    }
    with (
        patch(f"{_MOD}.object_session", return_value=MagicMock()),
        patch(f"{_MOD}._build_ise_services", return_value=(device_service, nautobot)),
    ):
        with pytest.raises(InventoryEvaluationError):
            await call_step(mod.execute, config, make_context(), run=make_run())
    assert nautobot.preview_inventory.call_args.kwargs == {"strict": True}
