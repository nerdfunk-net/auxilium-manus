"""Tests for RunService's pre-run validation gate — see
doc/ai_collaboration/PROCESS.md's "Pre-run validation gate" and
doc/ai_collaboration/VALIDATION_PLAN.md's "Frontend surfacing" bullet 3. Refuses
to dispatch a run when WorkflowValidationService reports an unresolved Tier
1-3 error, unconditionally (no override) — see
RunService._assert_no_blocking_validation_errors.

WorkflowValidationService itself is mocked at the module boundary (its own
behavior is covered by tests/unit/test_workflow_validation_service.py); this
file only tests that RunService calls it correctly and turns has_errors=True
into a refusal, before any run row is created."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.domain_exceptions import ValidationFailedError
from core.models.background_tier import WorkflowBackgroundTier
from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from core.models.workflows import Workflow
from models.runs import WorkflowRunCreate
from models.workflow_validation import ValidationFinding, WorkflowValidationResult
from services.execution.run_service import RunService

USER_ID = 1


def _result(*findings: ValidationFinding) -> WorkflowValidationResult:
    return WorkflowValidationResult(
        findings=list(findings), has_errors=any(f.severity == "error" for f in findings)
    )


def _error_finding(
    code: str = "credential_reference_not_found", message: str = "boom"
) -> ValidationFinding:
    return ValidationFinding(node_id="n1", tier=2, severity="error", code=code, message=message)


class RunServicePreRunValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Workflow.__table__,
                WorkflowRun.__table__,
                WorkflowStepResult.__table__,
                WorkflowBackgroundTier.__table__,
            ],
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)

        self.service = RunService(self.db)

        fake_ref = MagicMock(workflow_run_id="hatchet-run-1")
        run_no_wait_patch = patch(
            "hatchet.workflows.workflow_run.workflow.run_no_wait", return_value=fake_ref
        )
        self.mock_run_no_wait = run_no_wait_patch.start()
        self.addCleanup(run_no_wait_patch.stop)

    def _make_workflow(self, nodes: list | None = None) -> Workflow:
        workflow = Workflow(
            name="wf-1",
            creator_id=USER_ID,
            visibility="public",
            canvas_nodes=nodes
            or [{"id": "n1", "data": {"kind": "run-command", "pluginConfig": {}}}],
            canvas_edges=[],
        )
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def test_blocking_error_refuses_before_any_run_row_is_created(self) -> None:
        workflow = self._make_workflow()

        with patch(
            "services.execution.run_service.WorkflowValidationService"
        ) as mock_validator_cls:
            mock_validator_cls.return_value.validate.return_value = _result(_error_finding())

            with self.assertRaises(ValidationFailedError) as ctx:
                self.service.trigger_run(
                    workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
                )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("credential_reference_not_found", ctx.exception.detail)
        self.mock_run_no_wait.assert_not_called()
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_clean_validation_allows_dispatch(self) -> None:
        workflow = self._make_workflow()

        with patch(
            "services.execution.run_service.WorkflowValidationService"
        ) as mock_validator_cls:
            mock_validator_cls.return_value.validate.return_value = _result()

            response = self.service.trigger_run(
                workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
            )

        self.mock_run_no_wait.assert_called_once()
        self.assertEqual(self.db.query(WorkflowRun).count(), 1)
        self.assertIsNotNone(response.id)

    def test_warning_only_findings_never_block(self) -> None:
        workflow = self._make_workflow()
        warning = ValidationFinding(
            node_id="n1", tier=4, severity="warning", code="stale_reference", message="fyi"
        )

        with patch(
            "services.execution.run_service.WorkflowValidationService"
        ) as mock_validator_cls:
            mock_validator_cls.return_value.validate.return_value = _result(warning)

            self.service.trigger_run(
                workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
            )

        self.mock_run_no_wait.assert_called_once()

    def test_acting_user_id_passed_through_is_the_triggering_user(self) -> None:
        workflow = self._make_workflow()

        with patch(
            "services.execution.run_service.WorkflowValidationService"
        ) as mock_validator_cls:
            mock_validator_cls.return_value.validate.return_value = _result()

            self.service.trigger_run(
                workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
            )

        _, kwargs = mock_validator_cls.return_value.validate.call_args
        self.assertEqual(kwargs["acting_user_id"], USER_ID)

    def test_no_injected_registry_falls_back_to_a_fresh_one(self) -> None:
        workflow = self._make_workflow()

        with (
            patch("services.execution.run_service.WorkflowValidationService") as mock_validator,
            patch("services.execution.run_service.PluginRegistryService") as mock_registry_cls,
            patch("services.execution.run_service.PluginRepository"),
        ):
            mock_validator.return_value.validate.return_value = _result()

            self.service.trigger_run(
                workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
            )

        mock_registry_cls.assert_called_once()

    def test_injected_registry_is_reused_not_rebuilt(self) -> None:
        workflow = self._make_workflow()
        injected_registry = MagicMock()
        service = RunService(self.db, injected_registry)

        with (
            patch("services.execution.run_service.WorkflowValidationService") as mock_validator,
            patch("services.execution.run_service.PluginRegistryService") as mock_registry_cls,
        ):
            mock_validator.return_value.validate.return_value = _result()

            service.trigger_run(
                workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
            )

        mock_registry_cls.assert_not_called()
        mock_validator.assert_called_once_with(self.db, injected_registry)


class RunServiceLinkedInventoryGateTests(unittest.TestCase):
    """End to end through the *real* validator and step registry (only the
    inventory lookup is faked): a workflow whose "Get from Nautobot" step links
    a saved inventory that no longer exists must be refused before any run row
    is created."""

    def setUp(self) -> None:
        RunServicePreRunValidationTests.setUp(self)  # same DB + Hatchet stubs

        inventory_patches = [
            patch("services.sources.nautobot.persistence_service.InventoryService"),
            patch("repositories.inventory_repository.InventoryRepository"),
            patch("repositories.user_repository.UserRepository"),
            patch("repositories.settings_repository.SettingsRepository.get_by_key"),
        ]
        started = [p.start() for p in inventory_patches]
        for p in inventory_patches:
            self.addCleanup(p.stop)
        self.inventories = started[0].return_value
        started[2].return_value.get_by_id.return_value = MagicMock(username="alice")
        started[3].return_value = MagicMock()  # the Nautobot source exists

    _make_workflow = RunServicePreRunValidationTests._make_workflow

    def _workflow_linking(self, **config) -> Workflow:
        config = {"nautobot_source_id": "nautobot", **config}
        return self._make_workflow(
            [{"id": "n1", "data": {"kind": "get-nautobot-devices", "pluginConfig": config}}]
        )

    def _trigger(self, workflow: Workflow):
        return self.service.trigger_run(
            workflow_id=workflow.id, data=WorkflowRunCreate(), user_id=USER_ID
        )

    def test_a_deleted_inventory_refuses_the_run_before_any_row_is_created(self) -> None:
        self.inventories.get_inventory.return_value = None
        workflow = self._workflow_linking(inventory_id=2, inventory_name="Full lab env")

        with self.assertRaises(ValidationFailedError) as ctx:
            self._trigger(workflow)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("inventory_not_found", ctx.exception.detail)
        self.assertIn("Full lab env", ctx.exception.detail)
        self.assertIn("does not exist", ctx.exception.detail)
        self.mock_run_no_wait.assert_not_called()
        self.assertEqual(self.db.query(WorkflowRun).count(), 0)

    def test_an_existing_inventory_lets_the_run_dispatch(self) -> None:
        self.inventories.get_inventory.return_value = {"id": 1, "is_active": True}

        response = self._trigger(self._workflow_linking(inventory_id=1, inventory_name="LAB"))

        self.mock_run_no_wait.assert_called_once()
        self.assertIsNotNone(response.id)

    def test_a_step_with_no_inventory_is_not_blocked_by_this_check(self) -> None:
        self.inventories.get_inventory.return_value = None

        self._trigger(self._workflow_linking())

        self.inventories.get_inventory.assert_not_called()
        self.mock_run_no_wait.assert_called_once()


if __name__ == "__main__":
    unittest.main()
