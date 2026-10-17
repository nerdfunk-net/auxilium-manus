"""Node configuration booleans are real booleans on save and on read (C12-01)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.domain_exceptions import ValidationFailedError
from models.workflows import WorkflowCreate, WorkflowUpdate
from services.workflow.config_normalisation import (
    default_plugin_lookup,
    normalise_canvas_nodes,
    normalise_plugin_config,
)
from services.workflow.workflow_git_service import WorkflowGitSyncResult
from services.workflow.workflow_service import WorkflowService, _to_response


def _node(kind: str, **config: object) -> dict:
    return {"id": "n1", "data": {"kind": kind, "pluginConfig": dict(config)}}


def test_string_flags_become_booleans_on_save() -> None:
    nodes = [
        _node(
            "update-content",
            fail_if_no_match="true",
            content_source="running_config",
        )
    ]
    out = normalise_canvas_nodes(nodes, strict=True)
    config = out[0]["data"]["pluginConfig"]
    assert config["fail_if_no_match"] is True
    assert config["content_source"] == "running_config"  # not a boolean field: untouched
    assert nodes[0]["data"]["pluginConfig"]["fail_if_no_match"] == "true"  # input not mutated


def test_false_strings_are_false() -> None:
    out = normalise_canvas_nodes([_node("update-content", fail_if_no_match="No")], strict=True)
    assert out[0]["data"]["pluginConfig"]["fail_if_no_match"] is False


def test_unknown_string_is_rejected_with_the_key_name() -> None:
    with pytest.raises(ValueError, match="fail_if_no_match must be true or false"):
        normalise_canvas_nodes([_node("update-content", fail_if_no_match="ture")], strict=True)


def test_unknown_string_is_left_alone_on_read() -> None:
    out = normalise_canvas_nodes([_node("update-content", fail_if_no_match="ture")], strict=False)
    assert out[0]["data"]["pluginConfig"]["fail_if_no_match"] == "ture"


def test_non_boolean_fields_and_unknown_kinds_are_untouched() -> None:
    nodes = [_node("update-content", content_source="true"), _node("no-such-step", x="true")]
    assert normalise_canvas_nodes(nodes, strict=True) == nodes


def test_real_booleans_and_plain_nodes_pass_through() -> None:
    nodes = [_node("update-content", fail_if_no_match=False), {"id": "g", "data": {}}]
    assert normalise_canvas_nodes(nodes, strict=True) == nodes


def test_plugin_level_helper_uses_the_registry_declaration() -> None:
    plugin = default_plugin_lookup("update-content")
    assert plugin is not None
    assert normalise_plugin_config(plugin, {"fail_if_no_match": "1"}, strict=True) == {
        "fail_if_no_match": True
    }


def _service(workflow=None) -> WorkflowService:
    service = WorkflowService(MagicMock())
    service.repo = MagicMock()
    service.repo.create.side_effect = lambda **kw: _persisted(kw["canvas_nodes"])
    service.repo.get_by_id.side_effect = lambda _id: (workflow or _persisted([]), "creator")
    service.git = MagicMock()
    service.git.sync_workflow_to_git.return_value = WorkflowGitSyncResult(status="ok")
    service.changes = MagicMock()
    return service


def _persisted(nodes: list[dict]):
    from datetime import UTC, datetime

    from core.models.workflows import Workflow

    return Workflow(
        id=1,
        uuid="u",
        name="w",
        creator_id=1,
        folder="/",
        visibility="private",
        canvas_nodes=nodes,
        canvas_edges=[],
        canvas_groups=[],
        static_attributes=[],
        is_version_controlled=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_create_stores_real_booleans() -> None:
    service = _service()
    service.create_workflow(
        WorkflowCreate(name="w", canvas_nodes=[_node("update-content", fail_if_no_match="true")]),
        user_id=1,
    )
    stored = service.repo.create.call_args.kwargs["canvas_nodes"]
    assert stored[0]["data"]["pluginConfig"]["fail_if_no_match"] is True


def test_update_rejects_an_unknown_flag_string_as_a_400() -> None:
    service = _service(_persisted([]))
    with pytest.raises(ValidationFailedError, match="fail_if_no_match"):
        service.update_workflow(
            1,
            WorkflowUpdate(canvas_nodes=[_node("update-content", fail_if_no_match="ture")]),
            user_id=1,
        )


def test_string_flags_become_booleans_on_read() -> None:
    workflow = _persisted([_node("update-content", fail_if_no_match="true")])
    response = _to_response(workflow, "creator")
    assert response.canvas_nodes[0]["data"]["pluginConfig"]["fail_if_no_match"] is True
    # the stored row is not rewritten by a read
    assert workflow.canvas_nodes[0]["data"]["pluginConfig"]["fail_if_no_match"] == "true"


def test_comparison_diff_key_is_not_a_config_input() -> None:
    for plugin_id in ("compare-data", "compare-pyats-snapshot"):
        plugin = default_plugin_lookup(plugin_id)
        assert plugin is not None
        names = [field.name for field in plugin.metadata.configuration_input]
        assert "comparison_diff_key" not in names
