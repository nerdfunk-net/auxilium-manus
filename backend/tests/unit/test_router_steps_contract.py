"""Router steps: empty branch and secret-bearing match text (P-T write-first, W10-02 / W10-03).

D2: a router with an empty branch answers every handle it declares and keeps the context.
``route-on-content`` already does; ``route-on-attribute`` returns a single ``success`` that
none of its handles is named after, so the branches hanging off it never receive the (empty)
context.
"""

from __future__ import annotations

import pytest

from services.artifacts import InMemoryArtifactService
from tests.unit._step_helpers import call_step, make_context, make_device
from tests.unit.test_route_on_content_executor import _device_with_config
from workflow_steps.route_on_attribute.executor import execute as route_on_attribute
from workflow_steps.route_on_content.executor import execute as route_on_content

_ROUTES = [
    {"outcome": "cisco", "values": ["ios"]},
    {"outcome": "arista", "values": ["eos"]},
]


@pytest.mark.asyncio
async def test_route_on_content_answers_every_handle_for_an_empty_branch() -> None:
    context = make_context(note="kept")

    outcomes = await call_step(route_on_content, {"pattern": "x"}, context)

    assert {o.name for o in outcomes} == {"match", "mismatch", "failure"}
    assert all(o.context.metadata["note"] == "kept" for o in outcomes)


@pytest.mark.asyncio
async def test_route_on_attribute_answers_every_declared_handle_for_an_empty_branch() -> None:
    config = {"attribute_path": "device.platform", "routes": _ROUTES, "default_outcome": "other"}
    context = make_context(note="kept")

    outcomes = await call_step(route_on_attribute, config, context)

    names = {o.name for o in outcomes}
    assert names == {"cisco", "arista", "other", "failure"}
    assert all(o.context.metadata["note"] == "kept" for o in outcomes)


@pytest.mark.asyncio
async def test_route_on_attribute_checks_its_config_before_the_empty_guard() -> None:
    # Parse first (W1-10): a broken config fails the same way with or without devices.
    reserved = {
        "attribute_path": "device.platform",
        "routes": _ROUTES,
        "default_outcome": "failure",
    }
    for config in ({"attribute_path": "device.platform", "routes": []}, reserved):
        with pytest.raises(ValueError, match="route-on-attribute"):
            await call_step(route_on_attribute, config, make_context())


@pytest.mark.asyncio
async def test_route_on_attribute_routes_a_device_by_value() -> None:
    config = {"attribute_path": "device.platform", "routes": _ROUTES}
    device = make_device("d1", platform="ios")

    outcomes = await call_step(route_on_attribute, config, make_context([device]))

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["cisco"]) == {"d1"}
    assert by_name["arista"] == {}


@pytest.mark.asyncio
async def test_route_on_content_does_not_store_the_matched_secret() -> None:
    artifacts = InMemoryArtifactService()
    device = await _device_with_config(
        artifacts, device_id="d1", content="tacacs-server host 10.0.0.5 key s3cr3t-key-value\n"
    )

    outcomes = await call_step(
        route_on_content,
        {"content_source": "running_config", "match_mode": "regex", "pattern": r"key \S+"},
        make_context([device]),
        artifact_service=artifacts,
        node_id="n",
    )

    entry = next(o for o in outcomes if o.name == "match").context.devices["d1"].parsed["n"]
    assert "s3cr3t-key-value" not in str(entry["content_match"].get("matched_text", ""))
