"""More SSH families against a real ``DeviceSessionPool`` (P-T, W13-01).

``test_step_real_session_pool.py`` covers ``run-command``. Here the config reads
(``get-device-configs``) and the config push (``merge-config``) go through the real pool with a
fake Netmiko session, so a step that stops passing the pool, or loses the credential reference
that keys it, is noticed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.workflow_context import DeviceStatus
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from services.network.netmiko.connection import ConfigResult
from services.network.netmiko.session_pool import DeviceSessionPool
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
    patch_ssh_credential,
)
from tests.unit.test_step_real_session_pool import FakeSession as _BaseSession
from workflow_steps.get_device_configs.executor import execute as get_device_configs
from workflow_steps.merge_config.executor import execute as merge_config

_CONFIGS = "workflow_steps.get_device_configs.executor"
_MERGE = "workflow_steps.merge_config.executor"


class FakeSession(_BaseSession):
    merged: list[str] = []

    def get_configs(self, **_kwargs: Any) -> ConfigResult:
        return ConfigResult(success=True, running_config=f"hostname {self.host}\n")

    def merge_running_config(self, source_filename: str, **_kwargs: Any) -> NetmikoCommandResult:
        FakeSession.merged.append(f"{self.host}:{source_filename}")
        return NetmikoCommandResult(success=True, output="[OK]", command_outputs={})


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[DeviceSessionPool]:
    # ``instances`` and ``refuse`` are read through the base class by its own methods.
    _BaseSession.instances = []
    _BaseSession.refuse = set()
    FakeSession.merged = []
    real = DeviceSessionPool(max_workers=2)
    with patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession):
        yield real
    await real.close()


def _devices(*names: str) -> Any:
    return make_context(
        [
            make_device(n, name=n, primary_ip4=f"10.0.0.{i}/24", network_driver="cisco_ios")
            for i, n in enumerate(names, start=1)
        ]
    )


@pytest.mark.asyncio
async def test_get_device_configs_reads_through_the_pool(pool: DeviceSessionPool) -> None:
    with patch_ssh_credential(_CONFIGS), patch_object_session():
        outcomes = await call_step(
            get_device_configs,
            {"credential_reference": "lab-ssh", "config_format": "running"},
            _devices("a", "b"),
            run=make_run(),
            device_sessions=pool,
        )

    assert [o.name for o in outcomes] == ["success"]
    assert {s.host for s in _BaseSession.instances} == {"10.0.0.1", "10.0.0.2"}
    assert pool.stats()["created_total"] == 2
    devices = outcomes[0].context.devices
    assert all(d.status == DeviceStatus.OK for d in devices.values())
    assert all(d.running_config_ref is not None for d in devices.values())


@pytest.mark.asyncio
async def test_merge_config_one_unreachable_device_fails_alone(pool: DeviceSessionPool) -> None:
    _BaseSession.refuse = {"10.0.0.2"}
    with patch_ssh_credential(_MERGE), patch_object_session():
        outcomes = await call_step(
            merge_config,
            {"credential_reference": "lab-ssh", "source_filename": "flash:partial.cfg"},
            _devices("a", "b", "c"),
            run=make_run(),
            device_sessions=pool,
        )

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"a", "c"}
    assert set(by_name["failure"]) == {"b"}
    assert sorted(FakeSession.merged) == [
        "10.0.0.1:flash:partial.cfg",
        "10.0.0.3:flash:partial.cfg",
    ]
