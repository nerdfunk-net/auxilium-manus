"""The release stamp pins a release to the workflow, its settings and every workflow it starts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.workflow.release_stamp import (
    MAX_STAMPED_WORKFLOWS,
    ReleaseTooLargeError,
    child_workflow_ids,
    compute_stamp,
    release_is_current,
    release_settings,
)


def starter(child_id: object) -> dict:
    return {
        "id": f"s{child_id}",
        "data": {"kind": "start-workflow", "pluginConfig": {"workflow_id": child_id}},
    }


def wf(workflow_id: int, nodes: list | None = None, **overrides):
    base = {
        "id": workflow_id,
        "canvas_nodes": nodes or [],
        "canvas_edges": [],
        "canvas_groups": [],
        "static_attributes": [],
        "ai_released": True,
        "ai_release_stamp": None,
        "ai_description": "Compare.",
        "ai_result_node_id": "cmp",
        "ai_devices_input": "devs",
        "ai_credential_inputs": ["cred"],
        "ai_allow_free_ip": False,
    }
    return SimpleNamespace(**{**base, **overrides})


def released(root, workflows: dict):
    load = workflows.get
    root.ai_release_stamp = compute_stamp(root, release_settings(root), load)
    return load


def test_a_release_is_current_until_something_it_is_made_of_changes() -> None:
    child = wf(2)
    root = wf(1, [starter(2)])
    load = released(root, {2: child})
    assert release_is_current(root, load)

    child.canvas_nodes = [{"id": "x"}]  # an edit of the child ends the parent's release
    assert not release_is_current(root, load)


def test_grandchildren_count_too() -> None:
    grandchild, child = wf(3), wf(2, [starter(3)])
    root = wf(1, [starter(2)])
    load = released(root, {2: child, 3: grandchild})

    grandchild.static_attributes = [{"name": "new"}]
    assert not release_is_current(root, load)


def test_the_root_definition_and_the_release_settings_are_pinned() -> None:
    for change in (
        {"canvas_nodes": [{"id": "n"}]},
        {"canvas_edges": [{"id": "e"}]},
        {"canvas_groups": [{"id": "g"}]},
        {"static_attributes": [{"name": "a"}]},
        {"ai_description": "Different."},
        {"ai_result_node_id": "other"},
        {"ai_devices_input": "other"},
        {"ai_credential_inputs": []},
        {"ai_allow_free_ip": True},
    ):
        root = wf(1)
        load = released(root, {})
        for key, value in change.items():
            setattr(root, key, value)
        assert not release_is_current(root, load), change


def test_the_order_of_the_credential_inputs_does_not_matter() -> None:
    root = wf(1, ai_credential_inputs=["a", "b"])
    load = released(root, {})
    root.ai_credential_inputs = ["b", "a"]
    assert release_is_current(root, load)


def test_an_unreleased_workflow_or_one_without_a_stamp_is_never_current() -> None:
    root = wf(1)
    load = released(root, {})
    root.ai_released = False
    assert not release_is_current(root, load)
    root.ai_released, root.ai_release_stamp = True, None
    assert not release_is_current(root, load)


def test_a_child_that_disappears_ends_the_release() -> None:
    child = wf(2)
    root = wf(1, [starter(2)])
    workflows = {2: child}
    load = released(root, workflows)
    del workflows[2]
    assert not release_is_current(root, load)


def test_cycles_and_missing_ids_do_not_loop() -> None:
    a, b = wf(1, [starter(2)]), wf(2, [starter(1)])
    load = released(a, {1: a, 2: b})
    assert release_is_current(a, load)


def test_child_ids_ignore_other_steps_and_bad_values() -> None:
    nodes = [
        starter(7),
        starter("8"),
        starter(0),
        starter(None),
        starter("x"),
        {"id": "o", "data": {"kind": "send-commands", "pluginConfig": {"workflow_id": 9}}},
        {"id": "p"},
    ]
    assert child_workflow_ids(nodes) == [7, 8]


def test_a_graph_wider_than_the_cap_cannot_be_pinned() -> None:
    ids = list(range(2, MAX_STAMPED_WORKFLOWS + 3))  # one more child than the cap allows
    root = wf(1, [starter(i) for i in ids])
    children = {i: wf(i) for i in ids}
    with pytest.raises(ReleaseTooLargeError):
        compute_stamp(root, release_settings(root), children.get)


def test_a_graph_exactly_at_the_cap_is_pinned() -> None:
    ids = list(range(2, MAX_STAMPED_WORKFLOWS + 1))
    root = wf(1, [starter(i) for i in ids])
    children = {i: wf(i) for i in ids}
    assert compute_stamp(root, release_settings(root), children.get)


def test_a_stored_stamp_on_a_too_wide_graph_is_never_current() -> None:
    ids = list(range(2, MAX_STAMPED_WORKFLOWS + 3))
    root = wf(1, [starter(i) for i in ids], ai_release_stamp="deadbeef")
    children = {i: wf(i) for i in ids}
    assert not release_is_current(root, children.get)
