"""P-S (D2, W11-12): a router on an empty branch answers every handle it declares.

Each handle carries the incoming context with its metadata unchanged, so the step behind it starts
with the run's data instead of a rebuilt, empty context.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from tests.unit._step_helpers import call_step, make_context, make_run

# step -> (a valid config, the handles it declares)
ROUTERS: dict[str, tuple[dict[str, Any], set[str]]] = {
    "route_on_attribute": (
        {
            "attribute_path": "device.network_driver",
            "routes": [{"outcome": "ios", "values": ["cisco_ios"]}],
            "default_outcome": "other",
        },
        {"ios", "other", "failure"},
    ),
    "route_on_content": ({"pattern": "tacacs-server"}, {"match", "mismatch", "failure"}),
    "list_contains": (
        {"list_path": "parsed.k.vlans", "value": "10"},
        {"match", "mismatch", "failure"},
    ),
    "compare_data": ({}, {"match", "mismatch", "failure"}),
    "login_successful": ({"credential_reference": "lab-ssh"}, {"success", "failure"}),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("step", sorted(ROUTERS))
async def test_every_declared_handle_keeps_the_context_and_its_metadata(step: str) -> None:
    config, handles = ROUTERS[step]
    module = importlib.import_module(f"workflow_steps.{step}.executor")
    context = make_context(run_id="run-keep", keep={"a": 1})

    outcomes = await call_step(module.execute, config, context, run=make_run())

    assert {o.name for o in outcomes} == handles
    for outcome in outcomes:
        assert outcome.context.devices == {}
        assert outcome.context.metadata == {"keep": {"a": 1}}
        assert outcome.context.run_id == "run-keep"
