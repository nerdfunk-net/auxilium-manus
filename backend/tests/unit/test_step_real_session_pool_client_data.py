"""``collect-client-data`` against a real ``DeviceSessionPool`` (P-T leftover, W13-01).

The unit tests replace ``NetmikoService`` with a scripted fake, so the pool the step is handed is
never touched. Here two switches are read through the real pool with a fake Netmiko session: a
step that stops passing the pool, or loses the credential reference that keys the sessions, is
noticed, and an unreachable switch fails alone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import Table, create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.client_data import ClientIpAddress
from models.workflow_context import DeviceStatus
from services.network.netmiko.connection import CommandResult
from services.network.netmiko.session_pool import DeviceSessionPool
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
    patch_ssh_credential,
)
from tests.unit.test_collect_client_data_executor import CORE1, TABLES
from tests.unit.test_step_real_session_pool import FakeSession as _BaseSession
from workflow_steps.collect_client_data.config import get_config
from workflow_steps.collect_client_data.executor import execute as collect_client_data

_MODULE = "workflow_steps.collect_client_data.executor"
_STORE = "workflow_steps.common.client_data_store"
_REFUSAL = "                ^\n% Invalid input detected at '^' marker.\n"


class FakeSession(_BaseSession):
    """A switch per host; a command that is not scripted is refused, like a real CLI."""

    scripts: dict[str, dict[str, str]] = {}

    def send_commands(self, commands: list[str], **_kwargs: Any) -> CommandResult:
        self.sent.append(list(commands))
        script = FakeSession.scripts.get(self.host, {})
        outputs = {c: script.get(c, _REFUSAL) for c in commands}
        return CommandResult(success=True, output="", command_outputs=outputs)


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[DeviceSessionPool]:
    # ``instances`` and ``refuse`` are read through the base class by its own methods.
    _BaseSession.instances = []
    _BaseSession.refuse = set()
    FakeSession.scripts = {}
    real = DeviceSessionPool(max_workers=2)
    with patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession):
        yield real
    await real.close()


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[t for t in TABLES if isinstance(t, Table)])
    factory = sessionmaker(bind=engine)
    with patch(f"{_STORE}.get_db_session", side_effect=lambda: factory()):
        yield factory
    engine.dispose()


def _switches(*names: str) -> Any:
    return make_context(
        [
            make_device(n, name=n, primary_ip4=f"10.0.0.{i}/24", network_driver="cisco_ios")
            for i, n in enumerate(names, start=1)
        ]
    )


def _config() -> dict[str, Any]:
    return {**get_config(), "credential_reference": "lab-ssh"}


@pytest.mark.asyncio
async def test_two_switches_are_read_through_the_pool_and_stored(
    pool: DeviceSessionPool, sessions: sessionmaker[Session]
) -> None:
    FakeSession.scripts = {"10.0.0.1": CORE1, "10.0.0.2": CORE1}
    with (
        patch_ssh_credential(_MODULE) as credential,
        patch_object_session(),
        patch.object(pool, "run_on_device", wraps=pool.run_on_device) as run_on_device,
    ):
        outcomes = await call_step(
            collect_client_data,
            _config(),
            _switches("a", "b"),
            run=make_run(id=9, triggered_by_id=4),
            device_sessions=pool,
        )

    assert [o.name for o in outcomes] == ["success"]
    assert {s.host for s in _BaseSession.instances} == {"10.0.0.1", "10.0.0.2"}
    assert pool.stats()["created_total"] == 2
    assert {c.kwargs["credential_reference"] for c in run_on_device.call_args_list} == {"lab-ssh"}
    assert credential.call_args.kwargs["acting_user_id"] == 4
    with sessions() as db:
        assert len(list(db.scalars(select(ClientIpAddress)))) > 0


@pytest.mark.asyncio
async def test_an_unreachable_switch_fails_alone(
    pool: DeviceSessionPool, sessions: sessionmaker[Session]
) -> None:
    FakeSession.scripts = {"10.0.0.1": CORE1}
    _BaseSession.refuse = {"10.0.0.2"}
    with patch_ssh_credential(_MODULE), patch_object_session():
        outcomes = await call_step(
            collect_client_data,
            _config(),
            _switches("a", "b"),
            device_sessions=pool,
        )

    by_name = {o.name: o for o in outcomes}
    assert list(by_name["success"].context.devices) == ["a"]
    assert by_name["failure"].context.devices["b"].status == DeviceStatus.FAILED
