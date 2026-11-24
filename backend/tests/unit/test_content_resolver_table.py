"""W2-04: one table drives the node-result content sources; messages name the asking step."""

from __future__ import annotations

import pytest

from models.workflow_context import ArtifactRef, DeviceContext, DeviceStatus
from workflow_steps.common.content_resolver import (
    CONTENT_SOURCES,
    list_exportable_content,
    parse_content_source,
)

_NODE_RESULT_SOURCES = ("merged_content", "comparison_diff", "filtered_output", "updated_content")


def _ref(artifact_id: str = "a1") -> dict:
    return ArtifactRef(
        artifact_id=artifact_id, kind="x", media_type="text/plain", size_bytes=3
    ).model_dump(mode="json")


def _device(source: str, entry: object) -> DeviceContext:
    return DeviceContext(
        id="d1", name="d1", hostname="d1", status=DeviceStatus.OK, parsed={"n1": {source: entry}}
    )


@pytest.mark.parametrize("source", _NODE_RESULT_SOURCES)
def test_a_producer_entry_is_found_with_its_kind_and_node(source: str) -> None:
    entry = {"artifact_ref": _ref(), "kind": source, "reference_path": "ref/a.cfg"}
    (item,) = list_exportable_content(
        _device(source, entry), content_source=source, source_step_node_id="n1", step_id="s"
    )
    assert item.kind == source
    assert item.artifact_ref.artifact_id == "a1"
    assert item.media_type == "text/plain"
    expected = {"content_source": source, "source_step_node_id": "n1"}
    if source == "comparison_diff":
        expected["reference_path"] = "ref/a.cfg"
    assert item.extra == expected


@pytest.mark.parametrize("source", _NODE_RESULT_SOURCES)
@pytest.mark.parametrize(
    "entry",
    [
        None,
        "text",
        {"artifact_ref": None, "kind": "K"},
        {"artifact_ref": {"artifact_id": ""}, "kind": "K"},
        {"artifact_ref": _ref(), "kind": "other"},
        {"artifact_ref": _ref()},
    ],
)
def test_a_missing_or_foreign_entry_is_not_content(source: str, entry: object) -> None:
    if isinstance(entry, dict) and entry.get("kind") == "K":
        entry = {**entry, "kind": source}
    items = list_exportable_content(
        _device(source, entry), content_source=source, source_step_node_id="n1", step_id="s"
    )
    assert items == []


@pytest.mark.parametrize(
    "source",
    [*_NODE_RESULT_SOURCES, "command_output", "rendered_template", "pyats_snapshot"],
)
def test_a_source_that_needs_a_node_says_which_step_asked(source: str) -> None:
    device = DeviceContext(id="d1", name="d1", hostname="d1")
    with pytest.raises(
        ValueError, match=rf"^compare-data: source_step_node_id is required for {source}$"
    ):
        list_exportable_content(device, content_source=source, step_id="compare-data")


def test_sources_without_a_node_do_not_need_one() -> None:
    device = DeviceContext(id="d1", name="d1", hostname="d1")
    for source in ("running_config", "startup_config", "latest_command_output"):
        assert list_exportable_content(device, content_source=source, step_id="s") == []


def test_parse_content_source_names_the_step() -> None:
    with pytest.raises(ValueError, match=r"^route-on-content: content_source 'x' must be one of"):
        parse_content_source({"content_source": "x"}, step_id="route-on-content")


def test_parse_content_source_takes_the_allowed_set() -> None:
    allowed = frozenset({"running_config", "startup_config"})
    assert (
        parse_content_source({"content_source": "STARTUP_CONFIG"}, step_id="s", allowed=allowed)
        == "startup_config"
    )
    with pytest.raises(
        ValueError, match=r"^merge-content: content_source 'merged_content' must be"
    ):
        parse_content_source(
            {"content_source": "merged_content"}, step_id="merge-content", allowed=allowed
        )


def test_the_known_sources_are_unchanged() -> None:
    assert "merged_content" in CONTENT_SOURCES
    assert len(CONTENT_SOURCES) == 10
