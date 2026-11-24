"""W4-13 / W7-09: `output_key` is validated like every sibling step does, before any Batfish work.

A key with a dot is unreachable (`parsed.a.b.x` nests) and one with a dash is not a Jinja name;
the nine Batfish steps and `undefined-and-unused` (Undefined & Unused) used it verbatim.
"""

from __future__ import annotations

import importlib

import pytest

from tests.unit._step_helpers import call_step, make_context, make_device

_STEPS = [
    "batfish_acl_check",
    "batfish_bgp_facts",
    "batfish_extract_facts",
    "batfish_interface_properties",
    "batfish_node_properties",
    "batfish_ospf_facts",
    "batfish_path_check",
    "batfish_routing_table",
    "batfish_validate_facts",
    "undefined_and_unused",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("step", _STEPS)
@pytest.mark.parametrize("bad_key", ["a.b", "my-key", "1abc", "with space"])
async def test_a_bad_output_key_is_a_config_error_before_any_work(step: str, bad_key: str) -> None:
    module = importlib.import_module(f"workflow_steps.{step}.executor")
    context = make_context([make_device("d1")])
    with pytest.raises(ValueError, match="output_key"):
        await call_step(module.execute, {"output_key": bad_key}, context)


@pytest.mark.asyncio
@pytest.mark.parametrize("step", _STEPS)
async def test_the_default_key_passes_validation(step: str) -> None:
    # Whatever the step does next (here: no source configured), it is not the key.
    module = importlib.import_module(f"workflow_steps.{step}.executor")
    with pytest.raises(Exception) as caught:
        await call_step(module.execute, {}, make_context([make_device("d1")]))
    assert "output_key" not in str(caught.value)
