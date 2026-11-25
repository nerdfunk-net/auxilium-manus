"""D8 (W14-03): the backend defaults are authoritative.

The config panels no longer write their defaults into a node when it is opened, so a saved node
may lack every key the step has a default for. For each step whose panel used to seed itself, a
config without the defaults must behave like the same config with ``get_config()`` merged under
it: the same outcomes, devices and errors, or the same refusal.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from tests.unit._step_helpers import call_step, make_context, make_device, make_run

# Not here: ``get-from-user`` (its ``device_param`` is read by the run-input dialog, the AI
# release and the canvas migration, so it stays an explicit saved key; new nodes get it from
# ``use-canvas-steps`` and ``migrate-canvas``), and ``route-on-attribute`` /
# ``render-jinja-template`` (their panels write derived node state, ``outcomes`` /
# ``producesParsed``, which stays).

# Step -> the keys a run cannot do without (a user choice, no default exists).
REQUIRED: dict[str, dict[str, Any]] = {
    "add_nautobot_metadata": {"nautobot_source_id": "nb"},
    "add_to_nautobot": {"nautobot_source_id": "nb"},
    "compare_pyats_snapshot": {"features": ["ospf"]},
    "deploy_rendered_template": {"source_step_node_id": "render-1"},
    "from_change_request": {},
    "get_from_list": {"devices": [{"name": "r1", "ip_address": "10.0.0.1"}]},
    "git_push": {},
    "log_attributes": {},
    "log_message": {},
    "merge_content": {},
    "open_change_request": {},
    "update_attribute": {},
    "upload_config": {"source_step_node_id": "render-1"},
}


async def _observe(step: str, config: dict[str, Any]) -> str:
    executor = importlib.import_module(f"workflow_steps.{step}.executor")
    context = make_context([make_device("d1")])
    run = make_run(run_inputs={"target_devices": "r1,10.0.0.1"})
    try:
        outcomes = await call_step(executor.execute, config, context, run=run)
    except Exception as exc:  # the refusal itself is what is compared
        return f"{type(exc).__name__}: {exc}"
    return repr(
        [
            (
                outcome.name,
                {
                    k: (d.status, [(e.code, e.message) for e in d.errors], d.name)
                    for k, d in outcome.context.devices.items()
                },
            )
            for outcome in outcomes
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("step", sorted(REQUIRED))
async def test_missing_keys_behave_like_the_defaults(step: str) -> None:
    defaults = importlib.import_module(f"workflow_steps.{step}.config").get_config()
    base = REQUIRED[step]
    bare = await _observe(step, dict(base))
    seeded = await _observe(step, {**defaults, **base})
    assert bare == seeded
