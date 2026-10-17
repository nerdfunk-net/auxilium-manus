"""S2-11 / S2-10: administrator override for workflows, atomic last-admin check."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.domain_exceptions import AccessDeniedError
from core.models.workflows import Workflow
from services.workflow.workflow_service import WorkflowService


def _service(workflow: Workflow) -> WorkflowService:
    service = WorkflowService(MagicMock())
    service.repo = MagicMock()
    service.repo.get_by_id.return_value = (workflow, "creator")
    return service


def test_admin_can_delete_workflow_of_other_user() -> None:
    wf = Workflow(id=5, creator_id=1, visibility="private", name="w")
    service = _service(wf)
    with (
        patch("services.auth.rbac_service.RBACService.has_role", return_value=True),
        patch("services.workflow.workflow_service.ScheduleService"),
        patch("services.workflow.workflow_service.BackgroundTierService"),
        patch("services.workflow.workflow_service.RunRepository") as run_repo,
    ):
        run_repo.return_value.has_active_runs.return_value = False
        service.delete_workflow(5, user_id=2)
    service.repo.delete.assert_called_once_with(wf)


def test_delete_refused_while_a_run_is_active() -> None:
    from core.domain_exceptions import ConflictError

    wf = Workflow(id=5, creator_id=1, visibility="private", name="w")
    service = _service(wf)
    with (
        patch("services.auth.rbac_service.RBACService.has_role", return_value=True),
        patch("services.workflow.workflow_service.ScheduleService") as schedules,
        patch("services.workflow.workflow_service.RunRepository") as run_repo,
        pytest.raises(ConflictError),
    ):
        run_repo.return_value.has_active_runs.return_value = True
        service.delete_workflow(5, user_id=2)
    service.repo.delete.assert_not_called()
    schedules.assert_not_called()


def test_non_admin_still_cannot() -> None:
    wf = Workflow(id=5, creator_id=1, visibility="public", name="w")
    service = _service(wf)
    with (
        patch("services.auth.rbac_service.RBACService.has_role", return_value=False),
        pytest.raises(AccessDeniedError),
    ):
        service.delete_workflow(5, user_id=2)
    service.repo.delete.assert_not_called()


def test_user_deletion_reassigns_workflows_to_the_acting_admin() -> None:
    from services.auth.rbac_service import RBACService
    from services.users.user_service import UserService

    svc = UserService(MagicMock())
    svc._repo = MagicMock()
    svc._rbac = MagicMock(spec=RBACService)
    svc._workflows = MagicMock()
    svc._inventories = MagicMock()
    svc._schedules = MagicMock()  # type: ignore[method-assign]
    svc.delete_user(9, actor_user_id=1)
    svc._workflows.reassign_creator.assert_called_once_with(9, 1)
    svc._schedules.return_value.delete_for_user.assert_called_once_with(9)


def test_assert_not_last_admin_takes_the_lock() -> None:
    from services.auth.rbac_service import RBACService

    svc = RBACService(MagicMock())
    svc._repo = MagicMock()
    svc._repo.get_role_by_name.return_value = None
    svc.assert_not_last_admin(3)
    svc._repo.lock_admin_role.assert_called_once()


def test_template_is_referenced_scans_canvas_nodes() -> None:
    from unittest.mock import MagicMock

    from repositories.workflow_repository import WorkflowRepository

    db = MagicMock()
    db.scalars.return_value = [
        [{"id": "a", "data": {"kind": "run-command", "pluginConfig": {"template_id": 7}}}],
        [
            {
                "id": "b",
                "data": {"kind": "render-jinja-template", "pluginConfig": {"template_id": "7"}},
            }
        ],
    ]
    repo = WorkflowRepository(db)
    assert repo.template_is_referenced(7) is True
    db.scalars.return_value = [
        [{"id": "a", "data": {"kind": "render-jinja-template", "pluginConfig": {"template_id": 8}}}]
    ]
    assert repo.template_is_referenced(7) is False
