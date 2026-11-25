"""The result store and the node device every Batfish step shares (W7-06, W2-11)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from models.workflow_context import ArtifactRef, Capability, DeviceStatus
from services.artifacts import InMemoryArtifactService
from tests.unit._step_helpers import make_context
from workflow_steps.common.batfish_context import devices_from_nodes
from workflow_steps.common.batfish_results import batfish_node_device, store_batfish_result


@pytest.mark.asyncio
async def test_store_writes_one_json_artifact_and_returns_its_entry() -> None:
    artifacts = InMemoryArtifactService()
    ref = ArtifactRef(
        artifact_id="a-1",
        kind="batfish_result",
        media_type="application/json",
        size_bytes=3,
        sha256="x",
    )
    with patch.object(artifacts, "store", AsyncMock(return_value=ref)) as store:
        entry = await store_batfish_result(
            artifacts,
            [{"Node": "r1", "When": object}],
            context=make_context(run_id="run-7"),
            node_id="n1",
            question="routes",
            row_count=1,
            action="PERMIT",
        )
    kwargs = store.await_args.kwargs
    assert (kwargs["kind"], kwargs["device_id"], kwargs["run_id"]) == (
        "batfish_result",
        "batfish-n1",
        "run-7",
    )
    assert kwargs["media_type"] == "application/json"
    assert json.loads(kwargs["content"])[0]["Node"] == "r1"
    assert kwargs["content"].startswith("[\n  {")  # indent=2; a non-JSON value is str()-ed
    assert list(entry) == ["kind", "question", "artifact_ref", "row_count", "action"]
    assert (entry["kind"], entry["question"]) == ("batfish_result", "routes")
    assert (entry["row_count"], entry["action"]) == (1, "PERMIT")
    assert entry["artifact_ref"] == ref.model_dump(mode="json")


def test_node_device_identity_and_optional_parsed_capability() -> None:
    plain = batfish_node_device("r1")
    assert (plain.id, plain.name, plain.hostname, plain.source) == ("r1", "r1", "r1", "batfish")
    assert plain.capabilities == {Capability.IDENTITY}
    assert plain.status is DeviceStatus.OK
    assert batfish_node_device("r1", parsed=True).capabilities == {
        Capability.IDENTITY,
        Capability.PARSED,
    }


def test_devices_from_nodes_dedupes_and_skips_blank_nodes() -> None:
    rows = [{"Node": "r1"}, {"Node": "r2"}, {"Node": "r1"}, {"Node": ""}, {}, {"Node": None}]
    devices = devices_from_nodes(rows)
    assert list(devices) == ["r1", "r2"]
    assert devices["r2"].source == "batfish"
