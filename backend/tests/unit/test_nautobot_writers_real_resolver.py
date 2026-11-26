"""W13-06 (1): the Nautobot writers run the real device resolver.

Every other test of ``update-nautobot-device`` (Update Nautobot Device) and
``update-config-context`` (Update Config Context) patches ``resolve_nautobot_device_id``, so the
strict lookup of W5-02 (two devices of one name fail instead of the first one being written) was
never exercised through the steps. Here only the GraphQL side of Nautobot is faked
(``FakeNautobotGraphQL``) and the write service is a mock that records what would be written.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from tests.unit._step_helpers import FakeNautobotGraphQL
from workflow_steps.update_config_context import executor as config_context
from workflow_steps.update_nautobot_device import executor as device_update

pytestmark = pytest.mark.asyncio

NB_1 = "11111111-1111-1111-1111-111111111111"
NB_2 = "22222222-2222-2222-2222-222222222222"
CONTEXT = WorkflowContext(run_id="r", workflow_id="w", devices={})


def _device(name: str = "sw1", ip: str | None = None) -> DeviceContext:
    return DeviceContext(
        id="ctx-1",
        name=name,
        hostname=name,
        primary_ip4=ip,
        source="ise",
        attribute_bags={"custom": {"ntp": {"server": "10.0.0.5"}}},
    )


def _device_update_service() -> MagicMock:
    service = MagicMock()
    service.update_device = AsyncMock(
        return_value={"device_id": NB_1, "device_name": "sw1", "interfaces_failed": 0}
    )
    return service


def _config_context_service() -> MagicMock:
    service = MagicMock()
    service.get_local_config_context = AsyncMock(return_value={})
    service.set_local_config_context = AsyncMock()
    return service


async def _update_device(
    nautobot: FakeNautobotGraphQL, device: DeviceContext | None, config: dict[str, Any]
) -> tuple[DeviceContext, MagicMock]:
    service = _device_update_service()
    _, result, _ = await device_update._update_one_device(
        device_key="sw1",
        device=device,
        config=config,
        context=CONTEXT,
        node_id="n",
        nautobot_service=nautobot,  # type: ignore[arg-type]
        credentials=MagicMock(),
        update_service=service,
        parsed=device_update._parse_config(config),
    )
    assert result is not None
    return result, service


async def _write_context(
    nautobot: FakeNautobotGraphQL, device: DeviceContext | None, config: dict[str, Any]
) -> tuple[DeviceContext, MagicMock]:
    service = _config_context_service()
    _, result, _ = await config_context._update_one_device(
        device_key="sw1",
        device=device,
        parsed=config_context._parse_config(config),
        context=CONTEXT,
        node_id="n",
        nautobot_service=nautobot,  # type: ignore[arg-type]
        credentials=MagicMock(),
        update_service=service,
    )
    assert result is not None
    return result, service


_DEVICE_CONFIG: dict[str, Any] = {
    "nautobot_source_id": "src-1",
    "update_fields": {"serial": {"enabled": True, "value": "ABC123"}},
}
_CONTEXT_CONFIG: dict[str, Any] = {
    "nautobot_source_id": "src-1",
    "mode": "write",
    "path": "ntp.server",
    "value_source": {"type": "attribute", "attribute_path": "custom.ntp"},
}


def _explicit(config: dict[str, Any], **identifier: str) -> dict[str, Any]:
    return {**config, "device_identifier": {"mode": "explicit", **identifier}}


def _written_id(service: MagicMock) -> str:
    return service.update_device.await_args.kwargs["device_identifier"]["id"]


class TestUpdateNautobotDevice:
    async def test_a_unique_name_is_written(self) -> None:
        nautobot = FakeNautobotGraphQL([{"id": NB_1, "name": "sw1"}])

        device, service = await _update_device(nautobot, _device(), _DEVICE_CONFIG)

        assert device.status == DeviceStatus.OK
        assert _written_id(service) == NB_1

    async def test_two_devices_of_one_name_fail_and_nothing_is_written(self) -> None:
        nautobot = FakeNautobotGraphQL([{"id": NB_1, "name": "sw1"}, {"id": NB_2, "name": "sw1"}])

        device, service = await _update_device(nautobot, _device(), _DEVICE_CONFIG)

        assert device.status == DeviceStatus.FAILED
        assert "2 Nautobot devices are named 'sw1'" in device.errors[-1].message
        service.update_device.assert_not_awaited()

    async def test_an_explicit_name_is_resolved_as_strictly(self) -> None:
        nautobot = FakeNautobotGraphQL([{"id": NB_1, "name": "sw1"}, {"id": NB_2, "name": "sw1"}])

        device, service = await _update_device(
            nautobot, None, _explicit(_DEVICE_CONFIG, name="sw1")
        )

        assert device.status == DeviceStatus.FAILED
        assert "2 Nautobot devices are named 'sw1'" in device.errors[-1].message
        service.update_device.assert_not_awaited()

    async def test_the_primary_address_decides_when_the_name_is_unknown(self) -> None:
        nautobot = FakeNautobotGraphQL(
            [{"id": NB_1, "name": "other"}, {"id": NB_2, "name": "core", "primary_ip4": "10.0.0.9"}]
        )

        device, service = await _update_device(
            nautobot, _device(name="sw1", ip="10.0.0.9/24"), _DEVICE_CONFIG
        )

        assert device.status == DeviceStatus.OK
        assert _written_id(service) == NB_2
        assert nautobot.queries == ["name", "primary_ip4"]

    async def test_nothing_found_is_not_found(self) -> None:
        nautobot = FakeNautobotGraphQL([{"id": NB_1, "name": "SW1"}])

        device, service = await _update_device(nautobot, _device(), _DEVICE_CONFIG)

        assert device.errors[-1].code == "not_found"
        service.update_device.assert_not_awaited()


class TestUpdateConfigContext:
    async def test_a_unique_name_is_written(self) -> None:
        nautobot = FakeNautobotGraphQL([{"id": NB_1, "name": "sw1"}])

        device, service = await _write_context(nautobot, _device(), _CONTEXT_CONFIG)

        assert device.status == DeviceStatus.OK
        assert service.set_local_config_context.await_args.args[0] == NB_1

    @pytest.mark.parametrize("explicit", [False, True])
    async def test_two_devices_of_one_name_fail_and_nothing_is_written(
        self, explicit: bool
    ) -> None:
        nautobot = FakeNautobotGraphQL([{"id": NB_1, "name": "sw1"}, {"id": NB_2, "name": "sw1"}])
        config = _explicit(_CONTEXT_CONFIG, name="sw1") if explicit else _CONTEXT_CONFIG

        device, service = await _write_context(nautobot, None if explicit else _device(), config)

        assert device.status == DeviceStatus.FAILED
        assert "2 Nautobot devices are named 'sw1'" in device.errors[-1].message
        service.set_local_config_context.assert_not_awaited()

    async def test_nothing_found_is_not_found(self) -> None:
        nautobot = FakeNautobotGraphQL([])

        device, service = await _write_context(nautobot, _device(ip="10.0.0.1"), _CONTEXT_CONFIG)

        assert device.errors[-1].code == "not_found"
        service.set_local_config_context.assert_not_awaited()
