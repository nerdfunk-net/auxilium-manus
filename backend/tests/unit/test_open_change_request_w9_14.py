"""W9-14: open-change-request (Open Change Request) leftovers.

* "every rendered template, whichever step rendered it" is a ``content_resolver`` mode
  (``any_source_step=True``, ``rendered_template`` only) instead of a private copy in the step;
* "the rendered files equal the base branch" is a ``None`` result of ``_stage_to_git``, not an
  exception used as control flow.
"""

from __future__ import annotations

import pytest

import workflow_steps.open_change_request.executor as step
from models.workflow_context import ArtifactRef, DeviceContext, DeviceStatus
from workflow_steps.common.content_resolver import list_exportable_content


def _entry(artifact_id: str, step_node_id: str, *, kind: str | None = "rendered_template") -> dict:
    entry = {
        "artifact_ref": ArtifactRef(
            artifact_id=artifact_id, kind="rendered_template", size_bytes=1
        ).model_dump(mode="json"),
        "step_node_id": step_node_id,
        "output_key": artifact_id,
    }
    if kind is not None:
        entry["kind"] = kind
    return entry


def _device() -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="d1",
        hostname="d1",
        status=DeviceStatus.OK,
        parsed={
            "a": _entry("a", "render-1"),
            "b": _entry("b", "render-2", kind=None),
            "c": _entry("c", "render-3", kind="comparison_diff"),
            "d": {"artifact_ref": {}, "step_node_id": "render-4"},
            "e": "not an entry",
        },
    )


def test_any_source_step_lists_every_rendered_template_with_its_own_producer() -> None:
    items = list_exportable_content(
        _device(), content_source="rendered_template", step_id="s", any_source_step=True
    )

    assert [(i.artifact_ref.artifact_id, i.extra["source_step_node_id"]) for i in items] == [
        ("a", "render-1"),
        ("b", "render-2"),
    ]
    assert all(i.kind == "rendered_template" for i in items)
    assert [i.extra["output_key"] for i in items] == ["a", "b"]


def test_any_source_step_honours_the_parsed_output_key() -> None:
    items = list_exportable_content(
        _device(),
        content_source="rendered_template",
        step_id="s",
        any_source_step=True,
        parsed_output_key="b",
    )

    assert [i.artifact_ref.artifact_id for i in items] == ["b"]


def test_a_named_source_step_still_filters_with_the_flag() -> None:
    items = list_exportable_content(
        _device(),
        content_source="rendered_template",
        step_id="s",
        source_step_node_id="render-2",
        any_source_step=True,
    )

    assert [i.artifact_ref.artifact_id for i in items] == ["b"]


def test_without_the_flag_a_source_step_is_still_required() -> None:
    with pytest.raises(ValueError, match="source_step_node_id is required"):
        list_exportable_content(_device(), content_source="rendered_template", step_id="s")


def test_the_flag_is_only_for_rendered_templates() -> None:
    with pytest.raises(ValueError, match="any_source_step"):
        list_exportable_content(
            _device(), content_source="command_output", step_id="s", any_source_step=True
        )


def test_the_step_keeps_no_private_copy_and_no_control_flow_exception() -> None:
    assert not hasattr(step, "_all_rendered_templates")
    assert not hasattr(step, "NothingToReview")
