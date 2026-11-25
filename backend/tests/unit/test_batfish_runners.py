"""The two Batfish step bodies: ``run_combined_facts_step`` and ``run_property_step``."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.artifacts import InMemoryArtifactService
from services.batfish.bgp_facts import BGP_QUESTION_SPECS
from services.batfish.interface_properties_spec import INTERFACE_PROPERTIES_SPEC
from tests.unit._step_helpers import make_context, make_run
from workflow_steps.common import batfish_combined_facts, batfish_properties
from workflow_steps.common.batfish_combined_facts import run_combined_facts_step
from workflow_steps.common.batfish_properties import run_property_step


def _snap() -> MagicMock:
    snap = MagicMock()
    snap.connection, snap.network, snap.snapshot = "conn", "net", "snap"
    return snap


async def _combined(config: dict[str, Any], *, default_config: dict[str, Any] | None = None):
    queries = {key: AsyncMock(return_value=[{"Node": "r1"}]) for key in BGP_QUESTION_SPECS}
    with (
        patch.object(batfish_combined_facts, "service_factory"),
        patch.object(
            batfish_combined_facts, "resolve_batfish_snapshot_ref", AsyncMock(return_value=_snap())
        ),
    ):
        outcomes = await run_combined_facts_step(
            step_id="batfish-bgp-facts",
            specs=BGP_QUESTION_SPECS,
            queries=queries,
            default_output_key="default_key",
            default_config=default_config or {},
            config=config,
            context=make_context(),
            run=make_run(),
            artifact_service=InMemoryArtifactService(),
            node_id="n1",
        )
    return outcomes, queries


@pytest.mark.asyncio
async def test_combined_every_question_is_on_by_default_and_gets_the_snapshot_and_nodes() -> None:
    outcomes, queries = await _combined({"nodes": "r1"})
    for query in queries.values():
        query.assert_awaited_once()
        assert query.await_args.args[1] == "conn"
        assert query.await_args.kwargs == {
            "batfish_network": "net",
            "snapshot": "snap",
            "nodes": "r1",
        }
    device = outcomes[1].context.devices["r1"]
    assert list(device.parsed["n1"]) == ["default_key"]


@pytest.mark.asyncio
async def test_combined_a_disabled_question_is_not_asked() -> None:
    _, queries = await _combined({"include_peers": False, "include_edges": "false"})
    assert queries["peers"].await_count == 0
    assert queries["edges"].await_count == 0
    assert queries["process"].await_count == 1
    assert queries["sessions"].await_count == 1


@pytest.mark.asyncio
async def test_combined_nothing_enabled_names_every_toggle() -> None:
    off = {f"include_{key}": False for key in BGP_QUESTION_SPECS}
    with pytest.raises(ValueError) as caught:
        await _combined(off)
    assert str(caught.value) == (
        "batfish-bgp-facts: at least one of include_process/include_peers/"
        "include_sessions/include_edges must be enabled"
    )


@pytest.mark.asyncio
async def test_combined_step_config_overrides_the_default_config() -> None:
    outcomes, queries = await _combined(
        {"output_key": "mine", "include_peers": True},
        default_config={"include_peers": False, "include_edges": False, "output_key": "dflt"},
    )
    assert queries["peers"].await_count == 1  # config wins over the default
    assert queries["edges"].await_count == 0  # the default applies where config is silent
    assert list(outcomes[1].context.devices["r1"].parsed["n1"]) == ["mine"]


async def _property(config: dict[str, Any], *, default_config: dict[str, Any] | None = None):
    query = AsyncMock(
        return_value=[{"Interface": {"hostname": "r1", "interface": "Gi0"}, "MTU": 1500}]
    )
    with (
        patch.object(batfish_properties, "service_factory"),
        patch.object(
            batfish_properties, "resolve_batfish_snapshot_ref", AsyncMock(return_value=_snap())
        ),
    ):
        outcomes = await run_property_step(
            step_id="batfish-interface-properties",
            spec=INTERFACE_PROPERTIES_SPEC,
            query=query,
            extra_filters=("interfaces",),
            default_output_key="default_key",
            default_config=default_config or {},
            config=config,
            context=make_context(),
            run=make_run(),
            artifact_service=InMemoryArtifactService(),
            node_id="n1",
        )
    return outcomes, query


@pytest.mark.asyncio
async def test_property_filters_are_forwarded_to_the_query() -> None:
    _, query = await _property({"nodes": "r1", "properties": "MTU", "interfaces": "Gi0"})
    assert query.await_args.kwargs == {
        "batfish_network": "net",
        "snapshot": "snap",
        "nodes": "r1",
        "properties": "MTU",
        "interfaces": "Gi0",
    }


@pytest.mark.asyncio
async def test_property_default_config_and_output_key() -> None:
    outcomes, _ = await _property({}, default_config={"properties": "MTU", "output_key": "dflt"})
    assert list(outcomes[1].context.devices["r1"].parsed["n1"]) == ["dflt"]
    outcomes, _ = await _property({})
    assert list(outcomes[1].context.devices["r1"].parsed["n1"]) == ["default_key"]
    outcomes, query = await _property(
        {"output_key": "mine"}, default_config={"properties": "MTU", "output_key": "dflt"}
    )
    assert list(outcomes[1].context.devices["r1"].parsed["n1"]) == ["mine"]
    assert query.await_args.kwargs["properties"] == "MTU"
