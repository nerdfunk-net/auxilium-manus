"""``discover-network`` against a real ``DeviceSessionPool`` (P-T leftover, W13-01).

The unit tests give the step an ``AsyncMock`` pool, so the log-out after each visit
(``pool.close_host``) is only checked as a call. Here the real pool opens a session per visited
device and the step must close every one of them before the next device is read.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

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
from tests.unit.test_step_real_session_pool import FakeSession as _BaseSession
from workflow_steps.discover_network.config import get_config
from workflow_steps.discover_network.executor import execute as discover_network

_MODULE = "workflow_steps.discover_network.executor"
_CDP = "show cdp neighbors detail"


def _row(name: str, ip: str) -> dict[str, str]:
    return {
        "neighbor_name": name,
        "mgmt_address": ip,
        "platform": "cisco WS-C3850",
        "local_interface": "Gi1/0/1",
        "neighbor_interface": "Gi1/0/2",
        "capabilities": "Router Switch IGMP",
    }


class FakeSession(_BaseSession):
    """A switch per host: answers the CDP command with that host's neighbours."""

    neighbours: dict[str, list[dict[str, str]]] = {}

    def send_commands(self, commands: list[str], **_kwargs: Any) -> CommandResult:
        self.sent.append(list(commands))
        rows = FakeSession.neighbours.get(self.host, [])
        return CommandResult(success=True, output="", command_outputs={_CDP: json.dumps(rows)})


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[DeviceSessionPool]:
    # ``instances`` and ``refuse`` are read through the base class by its own methods.
    _BaseSession.instances = []
    _BaseSession.refuse = set()
    FakeSession.neighbours = {}
    real = DeviceSessionPool(max_workers=2)
    with patch("services.network.netmiko.session_pool.NetmikoDeviceSession", FakeSession):
        yield real
    await real.close()


def _seed() -> Any:
    return make_context(
        [make_device("d1", name="A", primary_ip4="10.1.0.1/24", network_driver="cisco_ios")]
    )


def _config() -> dict[str, Any]:
    return {
        **get_config(),
        "credential_reference": "lab-ssh",
        "follow_neighbors": True,
        "permitted_prefixes": ["10.1.0.0/16"],
    }


@pytest.mark.asyncio
async def test_every_visited_device_is_logged_out_through_the_real_pool(
    pool: DeviceSessionPool,
) -> None:
    FakeSession.neighbours = {"10.1.0.1": [_row("B", "10.1.0.2")], "10.1.0.2": []}
    settings = MagicMock(discover_network_follow_enabled=True)
    with (
        patch(f"{_MODULE}.settings", settings),
        patch_ssh_credential(_MODULE) as credential,
        patch_object_session(),
        patch.object(pool, "run_on_device", wraps=pool.run_on_device) as run_on_device,
    ):
        outcomes = await call_step(
            discover_network,
            _config(),
            _seed(),
            run=make_run(id=9, triggered_by_id=4),
            device_sessions=pool,
        )

    ok = next(o for o in outcomes if o.name == "success").context.devices
    assert sorted(d.name for d in ok.values()) == ["A", "B"]
    # one session per visited host, read once, and none left open afterwards
    assert [s.host for s in _BaseSession.instances] == ["10.1.0.1", "10.1.0.2"]
    assert all(s.sent == [[_CDP]] for s in _BaseSession.instances)
    assert not any(s.alive for s in _BaseSession.instances)
    assert pool.stats()["open"] == 0
    assert credential.call_args.kwargs["acting_user_id"] == 4
    # the credential reference keys every session the crawl opens
    assert [c.kwargs["credential_reference"] for c in run_on_device.call_args_list] == [
        "lab-ssh",
        "lab-ssh",
    ]


@pytest.mark.asyncio
async def test_a_host_that_cannot_be_reached_is_closed_too_and_fails_alone(
    pool: DeviceSessionPool,
) -> None:
    FakeSession.neighbours = {"10.1.0.1": [_row("B", "10.1.0.2")]}
    _BaseSession.refuse = {"10.1.0.2"}
    settings = MagicMock(discover_network_follow_enabled=True)
    with (
        patch(f"{_MODULE}.settings", settings),
        patch_ssh_credential(_MODULE),
        patch_object_session(),
    ):
        outcomes = await call_step(discover_network, _config(), _seed(), device_sessions=pool)

    summary = outcomes[0].context.metadata["node-1.discovery"]
    assert [v["name"] for v in summary["visited"]] == ["A"]
    assert [(n["name"], n["reason"]) for n in summary["seen_not_visited"]] == [("B", "unreachable")]
    assert [s.host for s in _BaseSession.instances] == ["10.1.0.1", "10.1.0.2"]
    assert pool.stats()["open"] == 0
