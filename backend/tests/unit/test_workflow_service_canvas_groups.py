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

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.domain_exceptions import ConflictError
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
    service.repo.name_exists.return_value = False
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

    def test_keeps_an_empty_container_group(self) -> None:
        # Palette "Step Group": starts empty and must survive a save.
        group = {**_GROUP, "nodeIds": [], "isContainer": True}
        assert _repair_orphan_groups(_NODES, [group]) == [group]

    def test_keeps_a_container_group_reduced_to_one_member(self) -> None:
        group = {**_GROUP, "nodeIds": ["a", "deleted-node"], "isContainer": True}
        result = _repair_orphan_groups(_NODES, [group])
        assert result == [{**group, "nodeIds": ["a"]}]

    def test_still_drops_dangling_members_of_a_container_group(self) -> None:
        group = {**_GROUP, "nodeIds": ["deleted-1", "deleted-2"], "isContainer": True}
        assert _repair_orphan_groups(_NODES, [group])[0]["nodeIds"] == []

    def test_non_container_flag_values_still_dissolve(self) -> None:
        group = {**_GROUP, "nodeIds": ["a"], "isContainer": False}
        assert _repair_orphan_groups(_NODES, [group]) == []

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


class TestWorkflowServiceOptimisticConcurrency:
    def test_update_with_stale_expected_updated_at_is_a_conflict(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)
        stale = workflow.updated_at - timedelta(seconds=5)

        with pytest.raises(ConflictError):
            service.update_workflow(
                1, WorkflowUpdate(name="Renamed", expected_updated_at=stale), user_id=1
            )

        service.repo.update.assert_not_called()
        assert workflow.name == "Test Workflow"

    def test_update_with_matching_expected_updated_at_works(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)

        response = service.update_workflow(
            1,
            WorkflowUpdate(name="Renamed", expected_updated_at=workflow.updated_at),
            user_id=1,
        )

        assert response.name == "Renamed"
        assert "expected_updated_at" not in service.repo.update.call_args.args[1]

    def test_naive_database_timestamp_matches_the_aware_one(self) -> None:
        workflow = _persisted_workflow()
        aware = workflow.updated_at
        workflow.updated_at = aware.replace(tzinfo=None)  # SQLite returns naive datetimes
        service = _service_with_mocked_repo(workflow)

        response = service.update_workflow(
            1, WorkflowUpdate(name="Renamed", expected_updated_at=aware), user_id=1
        )

        assert response.name == "Renamed"

    def test_update_without_expected_updated_at_still_works(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)

        response = service.update_workflow(1, WorkflowUpdate(name="Renamed"), user_id=1)

        assert response.name == "Renamed"

    def test_ai_session_write_does_not_use_the_guard(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)
        service.ai_gate = SimpleNamespace(assert_may_write=lambda *_a, **_k: None)  # type: ignore[assignment]

        response = service.update_workflow_for_ai_session(
            1, WorkflowUpdate(name="By AI"), ai_user_id=9, actor_username="ai-assistant"
        )

        assert response.name == "By AI"


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


class TestWorkflowServiceFolderNormalisation:
    """``create`` stores an empty folder as the root; an update must not store it as ``""``.

    ``check_name_available`` and ``find_id_by_name`` compare against ``folder or "/"``, so a
    workflow saved with ``""`` would never be found again and could be duplicated.
    """

    @pytest.mark.parametrize("sent", ["", None])
    def test_update_stores_an_empty_folder_as_the_root(self, sent: str | None) -> None:
        workflow = _persisted_workflow(folder="/net")
        service = _service_with_mocked_repo(workflow)

        service.update_workflow(1, WorkflowUpdate(folder=sent), user_id=1)

        assert service.repo.update.call_args.args[1]["folder"] == "/"

    def test_update_keeps_a_real_folder(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)

        service.update_workflow(1, WorkflowUpdate(folder="/net"), user_id=1)

        assert service.repo.update.call_args.args[1]["folder"] == "/net"

    def test_update_that_does_not_mention_the_folder_leaves_it_alone(self) -> None:
        workflow = _persisted_workflow(folder="/net")
        service = _service_with_mocked_repo(workflow)

        service.update_workflow(1, WorkflowUpdate(name="Renamed"), user_id=1)

        assert "folder" not in service.repo.update.call_args.args[1]


class TestWorkflowServiceNameCollisionOnUpdate:
    """An update that changes name, folder or visibility must not land on another workflow.

    ``name_exists`` is the same rule the Save As name check uses (public: unique by name and
    folder, private: per creator). Without it, moving a legacy ``""`` folder to ``/`` (or a
    rename) can create a twin that ``find_id_by_name`` can no longer tell apart.
    """

    def test_rename_onto_an_existing_name_is_a_conflict(self) -> None:
        workflow = _persisted_workflow()
        service = _service_with_mocked_repo(workflow)
        service.repo.name_exists.return_value = True

        with pytest.raises(ConflictError):
            service.update_workflow(1, WorkflowUpdate(name="Taken"), user_id=1)

        service.repo.update.assert_not_called()
        service.repo.name_exists.assert_called_once_with(
            name="Taken", folder="/", visibility="private", creator_id=1, exclude_id=1
        )

    @pytest.mark.parametrize("legacy", ["", None])
    def test_moving_a_legacy_folder_onto_a_twin_in_the_root_is_a_conflict(
        self, legacy: str | None
    ) -> None:
        workflow = _persisted_workflow(folder="/net")
        service = _service_with_mocked_repo(workflow)
        service.repo.name_exists.return_value = True

        with pytest.raises(ConflictError):
            service.update_workflow(1, WorkflowUpdate(folder=legacy), user_id=1)

        service.repo.update.assert_not_called()

    def test_an_update_that_keeps_name_folder_and_visibility_is_not_checked(self) -> None:
        workflow = _persisted_workflow(folder="")  # legacy row, already read as "/"
        service = _service_with_mocked_repo(workflow)
        service.repo.name_exists.return_value = True  # would block if it were asked

        service.update_workflow(
            1,
            WorkflowUpdate(name=workflow.name, folder="/", description="new text"),
            user_id=1,
        )

        service.repo.name_exists.assert_not_called()
        service.repo.update.assert_called_once()

    def test_a_rename_on_a_legacy_folder_is_checked_against_the_root(self) -> None:
        service = _service_with_mocked_repo(_persisted_workflow(folder=""))
        service.update_workflow(1, WorkflowUpdate(name="Fresh"), user_id=1)
        service.repo.name_exists.assert_called_once_with(
            name="Fresh", folder="/", visibility="private", creator_id=1, exclude_id=1
        )

    def test_a_canvas_only_update_is_not_checked(self) -> None:
        service = _service_with_mocked_repo(_persisted_workflow())
        service.update_workflow(1, WorkflowUpdate(canvas_edges=[]), user_id=1)
        service.repo.name_exists.assert_not_called()

    def test_a_free_new_identity_is_saved(self) -> None:
        service = _service_with_mocked_repo(_persisted_workflow())
        response = service.update_workflow(
            1, WorkflowUpdate(name="Fresh", folder="/net", visibility="public"), user_id=1
        )
        assert response.name == "Fresh"
        service.repo.name_exists.assert_called_once_with(
            name="Fresh", folder="/net", visibility="public", creator_id=1, exclude_id=1
        )
