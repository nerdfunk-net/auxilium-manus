"""WorkflowService must repair canvas_groups referencing a deleted node.

The canvas UI's own delete path (use-canvas-node-changes.ts's removeRealNodes)
already keeps canvas_groups in sync when a human deletes a node through it.
An AI-authored patch (backend/scripts/ai_workflow_apply.py) — or any other
caller writing canvas_nodes/canvas_groups directly — bypasses that path
entirely, so WorkflowService._repair_orphan_groups is the backend-side
safety net. Modeled on test_workflow_service_git_sync.py's
WorkflowService(MagicMock()) + mocked-repo pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from core.models.workflows import Workflow
from models.workflows import WorkflowCreate, WorkflowUpdate
from services.workflow.workflow_git_service import WorkflowGitSyncResult
from services.workflow.workflow_service import WorkflowService, _repair_orphan_groups

_NODES = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
_GROUP = {
    "id": "group-1",
    "title": "My Group",
    "nodeIds": ["a", "b"],
    "entryNodeId": "a",
    "exitNodeId": "b",
    "position": {"x": 0, "y": 0},
    "parentGroupId": None,
}


def _persisted_workflow(**overrides) -> Workflow:
    workflow = Workflow(
        id=1,
        uuid="11111111-1111-1111-1111-111111111111",
        name="Test Workflow",
        creator_id=1,
        description=None,
        folder="/",
        visibility="private",
        canvas_nodes=_NODES,
        canvas_edges=[],
        canvas_groups=[_GROUP],
        static_attributes=[],
        is_version_controlled=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    for key, value in overrides.items():
        setattr(workflow, key, value)
    return workflow


def _apply_update(workflow: Workflow, fields: dict) -> Workflow:
    for key, value in fields.items():
        setattr(workflow, key, value)
    return workflow


def _service_with_mocked_repo(workflow: Workflow) -> WorkflowService:
    service = WorkflowService(MagicMock())
    service.repo = MagicMock()
    service.repo.get_by_id.return_value = (workflow, "creator")
    service.repo.create.return_value = workflow
    service.repo.update.side_effect = _apply_update
    service.git = MagicMock()
    service.git.sync_workflow_to_git.return_value = WorkflowGitSyncResult(status="ok")
    service.changes = MagicMock()
    return service


class TestRepairOrphanGroupsPure:
    def test_leaves_a_fully_valid_group_untouched(self) -> None:
        result = _repair_orphan_groups(_NODES, [_GROUP])
        assert result == [_GROUP]

    def test_drops_a_dangling_member_but_keeps_the_group(self) -> None:
        group = {**_GROUP, "nodeIds": ["a", "b", "deleted-node"]}
        result = _repair_orphan_groups(_NODES, [group])
        assert len(result) == 1
        assert result[0]["nodeIds"] == ["a", "b"]

    def test_dissolves_a_group_left_with_fewer_than_two_members(self) -> None:
        group = {**_GROUP, "nodeIds": ["a", "deleted-node"]}
        result = _repair_orphan_groups(_NODES, [group])
        assert result == []

    def test_dissolves_a_group_left_with_zero_members(self) -> None:
        group = {**_GROUP, "nodeIds": ["deleted-1", "deleted-2"]}
        result = _repair_orphan_groups(_NODES, [group])
        assert result == []

    def test_does_not_repair_entry_or_exit_node_id(self) -> None:
        # Deliberate — matches CanvasGroup's own documented contract: a
        # best-effort cache, re-checked strictly at save/run time, not here.
        group = {**_GROUP, "nodeIds": ["a", "b"], "entryNodeId": "deleted-node"}
        result = _repair_orphan_groups(_NODES, [group])
        assert result[0]["entryNodeId"] == "deleted-node"

    def test_empty_groups_list_stays_empty(self) -> None:
        assert _repair_orphan_groups(_NODES, []) == []


class TestWorkflowServiceRepairsOnUpdate:
    def test_deleting_a_member_node_repairs_the_group(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)

        response = service.update_workflow(
            1,
            WorkflowUpdate(canvas_nodes=[{"id": "b"}, {"id": "c"}], canvas_edges=[]),
            user_id=1,
        )

        assert response.canvas_groups == []

    def test_deleting_two_members_still_leaves_a_valid_group_intact(self) -> None:
        two_member_group = {**_GROUP, "nodeIds": ["a", "b", "c"]}
        workflow = _persisted_workflow(canvas_groups=[two_member_group])
        service = _service_with_mocked_repo(workflow)

        response = service.update_workflow(
            1,
            WorkflowUpdate(canvas_nodes=[{"id": "a"}, {"id": "c"}], canvas_edges=[]),
            user_id=1,
        )

        assert len(response.canvas_groups) == 1
        assert response.canvas_groups[0]["nodeIds"] == ["a", "c"]

    def test_patch_touching_only_canvas_groups_is_still_repaired(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)
        stale_group = {**_GROUP, "nodeIds": ["a", "no-such-node"]}

        response = service.update_workflow(
            1, WorkflowUpdate(canvas_groups=[stale_group]), user_id=1
        )

        assert response.canvas_groups == []

    def test_patch_not_touching_canvas_or_groups_leaves_groups_untouched(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)

        response = service.update_workflow(1, WorkflowUpdate(name="Renamed"), user_id=1)

        assert response.canvas_groups == [_GROUP]
        service.repo.update.assert_called_once()
        assert "canvas_groups" not in service.repo.update.call_args.args[1]


class TestWorkflowServiceRepairsOnCreate:
    def test_create_workflow_repairs_a_stale_group_in_the_initial_patch(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)
        stale_group = {**_GROUP, "nodeIds": ["a", "no-such-node"]}

        service.create_workflow(
            WorkflowCreate(name="New", canvas_nodes=_NODES, canvas_groups=[stale_group]),
            user_id=1,
        )

        assert service.repo.create.call_args.kwargs["canvas_groups"] == []
