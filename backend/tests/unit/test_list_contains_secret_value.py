"""W4-03: `list-contains` (List Contains) never copies a sealed `value` into `device.parsed`."""

from __future__ import annotations

import pytest

from services.workflow_context.secret_fields import seal_secret
from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.list_contains import executor as mod

_CONFIG = {"list_path": "custom.servers", "value": "{tacacs.key}"}


def _device(device_id: str, key: object):
    return make_device(
        device_id,
        attribute_bags={"tacacs": {"key": key}, "custom": {"servers": ["hunter2", "other"]}},
    )


@pytest.mark.asyncio
async def test_a_sealed_value_fails_that_device_and_is_stored_nowhere() -> None:
    context = make_context([_device("d1", seal_secret("hunter2")), _device("d2", "other")])
    outcomes = {o.name: o.context for o in await call_step(mod.execute, _CONFIG, context)}
    assert list(outcomes["match"].devices) == ["d2"]
    failed = outcomes["failure"].devices["d1"]
    assert failed.errors[-1].code == "value_is_secret"
    assert "hunter2" not in str(failed.errors)
    assert failed.parsed == {}


@pytest.mark.asyncio
async def test_a_plain_value_is_unchanged() -> None:
    context = make_context([_device("d1", "other")])
    outcomes = {o.name: o.context for o in await call_step(mod.execute, _CONFIG, context)}
    membership = outcomes["match"].devices["d1"].parsed["node-1"]["membership"]
    assert (membership["matched"], membership["value"]) == (True, "other")
