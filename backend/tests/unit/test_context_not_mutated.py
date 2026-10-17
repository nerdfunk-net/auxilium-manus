"""CF-02 step 6: the attribute writers never mutate their input (copy-on-write, C6R-01).

Sibling branches may hand the same DeviceContext object to several steps; this is only safe
because every writer returns a copy.
"""

from __future__ import annotations

import copy

from models.workflow_context import DeviceContext
from workflow_steps.common.attribute_defaults import merge_nautobot_defaults
from workflow_steps.common.attribute_merge import merge_into_device_attribute
from workflow_steps.common.attribute_write import set_device_attribute


def _device(name: str) -> DeviceContext:
    return DeviceContext(
        id=name,
        name=name,
        hostname=name,
        attribute_bags={"nautobot": {"site": {"name": "x", "tags": ["a"]}, "role": "core"}},
        parsed={"n1": {"k": {"deep": [1, 2]}}},
    )


def test_set_device_attribute_does_not_touch_input_or_sibling() -> None:
    a, b = _device("a"), _device("b")
    before_a, before_b = a.model_dump(mode="json"), b.model_dump(mode="json")
    out = set_device_attribute(a, "nautobot.site.name", "changed")
    assert a.model_dump(mode="json") == before_a
    assert b.model_dump(mode="json") == before_b
    assert out.attribute_bags["nautobot"]["site"]["name"] == "changed"


def test_merge_into_device_attribute_does_not_touch_input() -> None:
    a = _device("a")
    before = a.model_dump(mode="json")
    out = merge_into_device_attribute(
        a, "nautobot.site", {"name": "new", "extra": {"x": 1}}, overwrite=True
    )
    assert a.model_dump(mode="json") == before
    assert out.attribute_bags["nautobot"]["site"]["extra"] == {"x": 1}


def test_merge_nautobot_defaults_does_not_touch_inputs() -> None:
    existing = {"site": {"name": "x"}, "tags": ["a"]}
    defaults = {"site": {"name": "d", "extra": [1]}, "tags": ["b"]}
    existing_before, defaults_before = copy.deepcopy(existing), copy.deepcopy(defaults)
    merged = merge_nautobot_defaults(existing, defaults, overwrite=True)
    assert existing == existing_before
    assert defaults == defaults_before
    merged["site"]["extra"].append(2)
    assert defaults == defaults_before
