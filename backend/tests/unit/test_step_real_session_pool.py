"""SSH steps against a real ``DeviceSessionPool`` with a fake Netmiko handle (P-T, W13-01).

Every other step test hands the executor ``device_sessions=MagicMock()``; a step that stops
passing the pool, or passes it to the wrong place, would not be noticed there. Here the pool is
real (thread executor, session lock, reuse), only the Netmiko session object is faked.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio

from models.workflow_context import DeviceStatus
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from services.network.netmiko.session_pool import DeviceSessionPool
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
    patch_ssh_credential,
)
from workflow_steps.run_command.executor import execute as run_command

_RUN_COMMAND = "workflow_steps.run_command.executor"


class FakeSession:
    """Stands in for ``NetmikoDeviceSession``: no socket, records what the pool does to it."""

    instances: list[FakeSession] = []
    refuse: set[str] = set()

    def __init__(self, *, host: str, **_kwargs: Any) -> None:
        self.host = host
        self.alive = False
        self.connects = 0
        self.sent: list[list[str]] = []
        FakeSession.instances.append(self)

    def connect(self, **_kwargs: Any) -> None:
        if self.host in FakeSession.refuse:
            raise ConnectionError(f"cannot reach {self.host}")
        self.alive = True
        self.connects += 1

    def disconnect(self) -> None:
        self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def check_config_mode(self) -> bool:
        return False

    def send_commands(self, commands: list[str], **_kwargs: Any) -> NetmikoCommandResult:
        self.sent.append(list(commands))
        return NetmikoCommandResult(
            success=True,
            output="",
            command_outputs={c: f"{self.host}:{c}" for c in commands},
        )


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[DeviceSessionPool]:
    FakeSession.instances = []
    FakeSession.refuse = set()
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


async def _run(pool: DeviceSessionPool, context: Any, *, reference: str = "lab-ssh") -> Any:
    with patch_ssh_credential(_RUN_COMMAND) as credential, patch_object_session():
        outcomes = await call_step(
            run_command,
            {"credential_reference": reference, "commands": ["show version"], "parser": "none"},
            context,
            run=make_run(id=9, triggered_by_id=4),
            device_sessions=pool,
        )
    credential.assert_called_once()
    assert credential.call_args.kwargs["acting_user_id"] == 4
    return outcomes


@pytest.mark.asyncio
async def test_run_command_sends_through_the_pool_it_was_given(pool: DeviceSessionPool) -> None:
    outcomes = await _run(pool, _devices("a", "b"))

    assert [o.name for o in outcomes] == ["success"]
    assert {s.host for s in FakeSession.instances} == {"10.0.0.1", "10.0.0.2"}
    assert pool.stats()["created_total"] == 2
    assert all(s.sent == [["show version"]] for s in FakeSession.instances)
    assert all(d.status == DeviceStatus.OK for d in outcomes[0].context.devices.values())


@pytest.mark.asyncio
async def test_a_second_step_in_the_segment_reuses_the_live_session(
    pool: DeviceSessionPool,
) -> None:
    context = _devices("a")

    await _run(pool, context)
    await _run(pool, context)

    assert len(FakeSession.instances) == 1
    assert FakeSession.instances[0].connects == 1
    assert FakeSession.instances[0].sent == [["show version"], ["show version"]]


@pytest.mark.asyncio
async def test_two_credential_references_never_share_a_session(pool: DeviceSessionPool) -> None:
    context = _devices("a")

    await _run(pool, context, reference="lab-ssh")
    await _run(pool, context, reference="other-ssh")

    assert len(FakeSession.instances) == 2


@pytest.mark.asyncio
async def test_one_unreachable_device_fails_alone(pool: DeviceSessionPool) -> None:
    FakeSession.refuse = {"10.0.0.2"}

    outcomes = await _run(pool, _devices("a", "b", "c"))

    assert sorted(o.name for o in outcomes) == ["failure", "success"]
    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"a", "c"}
    assert set(by_name["failure"]) == {"b"}
    assert by_name["failure"]["b"].status == DeviceStatus.FAILED
