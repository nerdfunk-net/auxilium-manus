"""discover-network (W3b-03): the walk catches every error per device.

A visit that raises something other than ``VisitError`` (a bug, an unexpected library error) used
to propagate through ``asyncio.gather`` and lose every device visited in earlier levels. It now
fails that device only, with a fixed message and a ``FailureInfo`` (no exception text); a neighbour
lookup that raises leaves the neighbour as CDP reported it.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceContext, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult
from workflow_steps.discover_network.config import get_config
from workflow_steps.discover_network.crawler import Reading, Target, crawl
from workflow_steps.discover_network.executor import execute
from workflow_steps.discover_network.parsing import Neighbor
from workflow_steps.discover_network.scope import parse_prefixes

MODULE = "workflow_steps.discover_network.executor"
CDP = "show cdp neighbors detail"
SECRET = "s3cr3t-library-text 10.9.9.9"
IOS = "cisco WS-C3850-48P"


def _neighbor(name: str, ip: str) -> Neighbor:
    return Neighbor(
        name=name, ip=ip, platform=IOS, local_port="Gi1/0/1", remote_port="Gi1/0/2",
        capabilities=("bridge", "router"),
    )  # fmt: skip


def _seed(host: str, name: str) -> Target:
    return Target(name=name, host=host, device_type="cisco_ios", depth=0, discovered_from=None)


def _settings() -> Any:
    from workflow_steps.discover_network.crawler import CrawlSettings

    return CrawlSettings(
        follow=True,
        prefixes=parse_prefixes(["10.1.0.0/16"]),
        only_infrastructure=True,
        max_devices=50,
        max_depth=5,
        concurrency=3,
        override=None,
        host_policy=lambda host: None,
    )


@pytest.mark.asyncio
async def test_an_unexpected_visit_error_fails_that_seed_only() -> None:
    async def visit(target: Target) -> Reading:
        if target.host == "10.1.0.2":
            raise OSError(SECRET)
        return Reading(())

    result = await crawl([_seed("10.1.0.1", "A"), _seed("10.1.0.2", "B")], visit, _settings())

    assert [v.target.name for v in result.visited] == ["A"]
    ((target, error),) = result.failed_seeds
    assert target.name == "B"
    assert error.code == "unreachable"
    assert error.failure is not None
    assert error.failure.exception_type == "OSError"
    assert SECRET not in str(error.failure)


@pytest.mark.asyncio
async def test_an_unexpected_error_on_a_followed_neighbour_keeps_the_earlier_levels() -> None:
    async def visit(target: Target) -> Reading:
        if target.host == "10.1.0.2":
            raise KeyError(SECRET)
        return Reading((_neighbor("B", "10.1.0.2"),))

    result = await crawl([_seed("10.1.0.1", "A")], visit, _settings())

    assert [v.target.name for v in result.visited] == ["A"]
    assert [(s.name, s.reason) for s in result.seen] == [("B", "unreachable")]
    assert result.failed_seeds == ()


@pytest.mark.asyncio
async def test_a_lookup_that_raises_leaves_the_neighbour_and_is_reported() -> None:
    async def visit(target: Target) -> Reading:
        return Reading((_neighbor("B", "10.1.0.2"),) if target.host == "10.1.0.1" else ())

    async def resolve(neighbor: Neighbor) -> Neighbor:
        raise AttributeError(SECRET)

    result = await crawl([_seed("10.1.0.1", "A")], visit, _settings(), resolve=resolve)

    assert [v.target.name for v in result.visited] == ["A", "B"]
    assert result.resolve_errors == 1


def _row(name: str, ip: str) -> dict[str, str]:
    return {
        "neighbor_name": name, "mgmt_address": ip, "platform": IOS,
        "local_interface": "Gi1/0/1", "neighbor_interface": "Gi1/0/2",
        "capabilities": "Router Switch IGMP",
    }  # fmt: skip


class _Netmiko:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs

    async def send_commands(self, *, host: str, **kwargs: Any) -> CommandResult:
        return CommandResult(
            success=True, output="", command_outputs={CDP: self.outputs.get(host, "[]")}
        )


def _device(device_id: str, name: str, ip: str) -> DeviceContext:
    return DeviceContext(
        id=device_id, name=name, hostname=name, primary_ip4=f"{ip}/24", network_driver="cisco_ios"
    )


async def _execute(devices: dict[str, DeviceContext], netmiko: _Netmiko) -> list[Any]:
    run = MagicMock()
    run.id = 1
    run.run_inputs = {}
    run.triggered_by_id = 1
    config = {**get_config(), "credential_reference": "lab", "follow_neighbors": True}
    config["permitted_prefixes"] = ["10.1.0.0/16"]
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch(f"{MODULE}.resolve_ssh_credential", return_value=("admin", "secret")),
        patch(f"{MODULE}.settings", MagicMock(discover_network_follow_enabled=True)),
        patch(f"{MODULE}.NetmikoService", return_value=netmiko),
    ):
        return await execute(
            config=config,
            context=WorkflowContext(run_id="r", workflow_id="w", devices=devices),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id="disc-1",
            device_sessions=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_a_parser_bug_on_one_seed_fails_it_and_keeps_the_other() -> None:
    real = __import__(
        "workflow_steps.discover_network.executor", fromlist=["classify_cdp_output"]
    ).classify_cdp_output

    def classify(raw: str) -> Any:
        if "boom" in raw:
            raise TypeError(SECRET)
        return real(raw)

    netmiko = _Netmiko({"10.1.0.1": json.dumps([]), "10.1.0.2": "boom"})
    devices = {"a": _device("a", "A", "10.1.0.1"), "b": _device("b", "B", "10.1.0.2")}
    with patch(f"{MODULE}.classify_cdp_output", classify):
        outcomes = await _execute(devices, netmiko)

    by_name = {o.name: o for o in outcomes}
    assert set(by_name["success"].context.devices) == {"a"}
    error = by_name["failure"].context.devices["b"].errors[-1]
    assert error.code == "unreachable"
    assert SECRET not in error.message
    assert by_name["success"].summary == "visited 1 device(s), 0 seen but not visited"
    assert by_name["failure"].summary == "1 seed device(s) failed"
    assert "disc-1.discovery" in by_name["failure"].context.metadata


@pytest.mark.asyncio
async def test_a_failing_lookup_is_reported_as_unavailable_in_the_summary() -> None:
    netmiko = _Netmiko({"10.1.0.1": json.dumps([_row("B", "10.1.0.2")])})
    lookup = MagicMock()
    lookup.resolve = AsyncMock(side_effect=AttributeError(SECRET))
    lookup.unavailable = False
    with patch(f"{MODULE}._management_ip_lookup", return_value=(lookup, "on")):
        outcomes = await _execute({"a": _device("a", "A", "10.1.0.1")}, netmiko)

    summary = outcomes[0].context.metadata["disc-1.discovery"]
    assert summary["management_ip_lookup"] == "unavailable"
