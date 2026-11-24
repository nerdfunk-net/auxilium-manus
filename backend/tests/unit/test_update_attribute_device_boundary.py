"""W4-01: one device's data never aborts `update-attribute` (Update Attribute) for its siblings.

A sealed placeholder in template mode, a selector write into a bag of another shape and an
unexpected exception are conditions of *this* device: it leaves through ``failure`` with a
``DeviceError`` and the other devices keep going. Missing required fields are still a config
error, raised once before any device is touched.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from models.workflow_context import DeviceStatus
from services.workflow_context.secret_fields import seal_secret
from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.update_attribute import executor as mod

_TEMPLATE = {"mode": "template", "destination_path": "custom.copy", "template": "{tacacs.key}"}
_SELECTOR = {
    "mode": "fixed",
    "destination_path": "nautobot.interfaces[name=Gi0/0].mac",
    "fixed_value": "aa:bb",
}


async def _run(attribute: dict[str, Any], *devices):
    outcomes = await call_step(mod.execute, {"attributes": [attribute]}, make_context(devices))
    return {outcome.name: outcome.context for outcome in outcomes}


@pytest.mark.asyncio
async def test_template_with_a_sealed_placeholder_fails_only_that_device() -> None:
    sealed = make_device("d1", attribute_bags={"tacacs": {"key": seal_secret("hunter2")}})
    plain = make_device("d2", attribute_bags={"tacacs": {"key": "ok"}})
    out = await _run(_TEMPLATE, sealed, plain)
    assert list(out["success"].devices) == ["d2"]
    failed = out["failure"].devices["d1"]
    assert failed.status is DeviceStatus.FAILED
    assert failed.errors[-1].code == "source_is_secret"
    assert "hunter2" not in failed.errors[-1].message


@pytest.mark.asyncio
async def test_selector_write_into_a_bag_of_another_shape_fails_only_that_device() -> None:
    wrong_shape = make_device("d1", attribute_bags={"nautobot": {"interfaces": {"not": "a list"}}})
    fine = make_device("d2")
    out = await _run(_SELECTOR, wrong_shape, fine)
    assert list(out["success"].devices) == ["d2"]
    failed = out["failure"].devices["d1"]
    assert failed.errors[-1].code == "valueerror"
    assert "is not a list" in failed.errors[-1].message


@pytest.mark.asyncio
async def test_an_unexpected_exception_fails_the_device_with_its_class_name_only() -> None:
    def explode(device, path, value):
        if device.id == "d1":
            raise RuntimeError("secret detail: password=hunter2")
        return device

    with patch.object(mod, "set_device_attribute", side_effect=explode):
        out = await _run(
            {"mode": "fixed", "destination_path": "custom.x", "fixed_value": "v"},
            make_device("d1"),
            make_device("d2"),
        )
    assert list(out["success"].devices) == ["d2"]
    error = out["failure"].devices["d1"].errors[-1]
    assert (error.code, error.message) == ("runtimeerror", "RuntimeError")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attribute", "needle"),
    [
        ({"mode": "fixed", "destination_path": "x.y", "fixed_value": " "}, "fixed_value"),
        (
            {"mode": "regex", "destination_path": "x.y", "source_path": "a", "pattern": ""},
            "pattern",
        ),
        (
            {
                "mode": "regex",
                "destination_path": "x.y",
                "source_path": "a",
                "pattern": "p",
                "destination_template": "",
            },
            "destination_template",
        ),
        ({"mode": "template", "destination_path": "x.y", "template": " "}, "template"),
    ],
    ids=["fixed", "regex-pattern", "regex-template", "template"],
)
async def test_missing_required_fields_raise_once_before_any_device(
    attribute: dict[str, Any], needle: str
) -> None:
    with pytest.raises(ValueError, match=needle):
        mod._parse_attributes({"attributes": [attribute]})
    with pytest.raises(ValueError, match=needle):
        await _run(attribute, make_device("d1"), make_device("d2"))
