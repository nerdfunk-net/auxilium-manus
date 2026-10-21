"""Tests for services/execution/schedule_service.py."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from hatchet_sdk.clients.rest.exceptions import (
    ApiException,
    RestConnectionError,
    RestTimeoutError,
    ServiceException,
)

from core.domain_exceptions import AccessDeniedError, NotFoundError, ValidationFailedError
from models.schedules import WorkflowScheduleCreate, WorkflowScheduleUpdate
from services.execution.dispatch_breaker import ENGINE_UNAVAILABLE_MESSAGE
from services.execution.schedule_service import ScheduleService


def _workflow(visibility: str = "public", creator_id: int = 7, static_attributes=None) -> MagicMock:
    wf = MagicMock()
    wf.name = "Nightly Backup"
    wf.visibility = visibility
    wf.creator_id = creator_id
    wf.static_attributes = static_attributes or []
    return wf


def _schedule_row(**over) -> MagicMock:
    row = MagicMock()
    row.id = over.get("id", 3)
    row.uuid = over.get("uuid", "sch-uuid")
    row.workflow_id = over.get("workflow_id", 10)
    row.created_by_id = over.get("created_by_id", 7)
    row.name = over.get("name", "Site A")
    row.schedule_type = over.get("schedule_type", "cron")
    row.cron_expression = over.get("cron_expression", "0 8 * * *")
    row.run_at = over.get("run_at", None)
    row.enabled = over.get("enabled", True)
    row.run_inputs = over.get("run_inputs", {})
    row.hatchet_cron_id = over.get("hatchet_cron_id", None)
    row.hatchet_scheduled_id = over.get("hatchet_scheduled_id", None)
    row.last_triggered_at = over.get("last_triggered_at", None)
    row.created_at = over.get("created_at", datetime(2026, 1, 1, tzinfo=UTC))
    row.updated_at = over.get("updated_at", datetime(2026, 1, 2, tzinfo=UTC))
    return row


def _service() -> ScheduleService:
    svc = ScheduleService(MagicMock())
    svc.repo = MagicMock()
    svc.wf_repo = MagicMock()
    svc.tier_repo = MagicMock()
    svc.tier_repo.get_by_workflow_id.return_value = MagicMock(concurrency_limit=1)
    svc.wf_repo.get_by_id.return_value = (_workflow(), None)
    return svc


class ScheduleServiceCreateTests(unittest.TestCase):
    def setUp(self) -> None:
        p = patch("services.execution.schedule_service.hatchet")
        self.hatchet = p.start()
        self.hatchet.cron.create.return_value = MagicMock(metadata=MagicMock(id="cron-xyz"))
        self.addCleanup(p.stop)
        bt = patch("services.execution.schedule_service.BackgroundTierService")
        self.bg_cls = bt.start()
        self.addCleanup(bt.stop)

    def _create_data(self, **over) -> WorkflowScheduleCreate:
        base = dict(
            workflow_id=10,
            name="Site A",
            schedule_type="cron",
            cron_expression="0 8 * * *",
            enabled=True,
            run_inputs={},
            concurrency_limit=1,
        )
        base.update(over)
        return WorkflowScheduleCreate(**base)

    def test_create_publishes_to_background_tier(self) -> None:
        svc = _service()
        svc.repo.create.return_value = _schedule_row()
        svc.create_schedule(self._create_data(concurrency_limit=2), user_id=7)
        self.bg_cls.return_value.publish.assert_called_once()
        _wf_id, upsert, uid = self.bg_cls.return_value.publish.call_args[0]
        self.assertEqual(upsert.concurrency_limit, 2)
        self.assertEqual(uid, 7)

    def test_create_registers_cron_with_per_schedule_name(self) -> None:
        svc = _service()
        svc.repo.create.return_value = _schedule_row(id=3, workflow_id=10)
        svc.create_schedule(self._create_data(), user_id=7)
        kwargs = self.hatchet.cron.create.call_args.kwargs
        self.assertEqual(kwargs["cron_name"], "workflow-10-schedule-3")
        self.assertEqual(kwargs["input"], {"workflow_id": 10, "schedule_id": 3})

    def test_create_cron_without_expression_rejected(self) -> None:
        svc = _service()
        with self.assertRaises(ValidationFailedError):
            svc.create_schedule(
                self._create_data(schedule_type="cron", cron_expression=None), user_id=7
            )

    def test_create_once_in_the_past_rejected(self) -> None:
        svc = _service()
        past = datetime.now(UTC) - timedelta(hours=1)
        with self.assertRaises(ValidationFailedError):
            svc.create_schedule(
                self._create_data(schedule_type="once", cron_expression=None, run_at=past),
                user_id=7,
            )

    def test_create_bad_run_inputs_rejected(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (
            _workflow(static_attributes=[{"name": "vlan", "type": "number", "required": True}]),
            None,
        )
        with self.assertRaises(ValidationFailedError):
            svc.create_schedule(self._create_data(run_inputs={"vlan": "not-a-number"}), user_id=7)

    def test_create_private_workflow_other_user_denied(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = (_workflow("private", creator_id=1), None)
        with self.assertRaises(AccessDeniedError):
            svc.create_schedule(self._create_data(), user_id=99)

    def test_create_missing_workflow_raises(self) -> None:
        svc = _service()
        svc.wf_repo.get_by_id.return_value = None
        with self.assertRaises(NotFoundError):
            svc.create_schedule(self._create_data(), user_id=7)


class ScheduleServiceListDeleteTests(unittest.TestCase):
    def test_list_returns_every_schedule_for_a_workflow(self) -> None:
        svc = _service()
        svc.repo.list_visible.return_value = [
            (_schedule_row(id=1, name="Site A"), "Nightly Backup"),
            (_schedule_row(id=2, name="Site B"), "Nightly Backup"),
        ]
        out = svc.list_schedules(user_id=7, workflow_id=10)
        self.assertEqual([s.id for s in out], [1, 2])
        self.assertEqual(out[0].concurrency_limit, 1)

    def test_delete_for_workflow_unchecked_removes_all(self) -> None:
        svc = _service()
        rows = [_schedule_row(id=1), _schedule_row(id=2, hatchet_cron_id="c2")]
        svc.repo.list_by_workflow_id.return_value = rows
        with patch("services.execution.schedule_service.hatchet"):
            svc.delete_schedules_for_workflow_unchecked(10)
        self.assertEqual(svc.repo.delete.call_count, 2)

    def test_delete_missing_schedule_raises(self) -> None:
        svc = _service()
        svc.repo.get_by_id.return_value = None
        with self.assertRaises(NotFoundError):
            svc.delete_schedule(999, user_id=7)

    def test_delete_hatchet_entry_tolerates_404(self) -> None:
        from hatchet_sdk.clients.rest.exceptions import NotFoundException

        svc = _service()
        row = _schedule_row(id=5, hatchet_scheduled_id="sched-gone")
        with patch("services.execution.schedule_service.hatchet") as hatchet_mock:
            hatchet_mock.scheduled.delete.side_effect = NotFoundException(
                http_resp=None, body='{"message":"scheduled workflow run not found"}'
            )
            # Must not raise — the entry is already gone, which is the goal.
            svc._delete_hatchet_entry(row)


class ScheduleOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        p = patch("services.execution.schedule_service.hatchet")
        self.hatchet = p.start()
        self.addCleanup(p.stop)

    def test_user_b_cannot_update_or_delete_user_a_schedule(self) -> None:
        from core.domain_exceptions import AccessDeniedError

        svc = _service()
        svc.repo.get_by_id.return_value = _schedule_row(id=3, created_by_id=7)
        with patch("services.auth.rbac_service.RBACService.has_role", return_value=False):
            with self.assertRaises(AccessDeniedError):
                svc.update_schedule(3, WorkflowScheduleUpdate(name="x"), user_id=8)
            with self.assertRaises(AccessDeniedError):
                svc.delete_schedule(3, user_id=8)
        svc.repo.delete.assert_not_called()

    def test_admin_can_delete_and_it_is_logged(self) -> None:
        svc = _service()
        svc.repo.get_by_id.return_value = _schedule_row(id=3, created_by_id=7)
        with (
            patch("services.auth.rbac_service.RBACService.has_role", return_value=True),
            self.assertLogs("services.execution.schedule_service", level="WARNING") as logs,
        ):
            svc.delete_schedule(3, user_id=8)
        self.assertTrue(any("schedule_admin_override" in m for m in logs.output))
        svc.repo.delete.assert_called_once()

    def test_deactivating_and_deleting_user_stop_their_schedules(self) -> None:
        svc = _service()
        rows = [_schedule_row(id=1), _schedule_row(id=2)]
        svc.repo.list_by_creator.return_value = rows
        self.assertEqual(svc.disable_for_user(7), 2)
        self.assertEqual(svc.repo.update.call_count, 2)
        self.assertEqual(svc.delete_for_user(7), 2)
        self.assertEqual(svc.repo.delete.call_count, 2)


class ScheduleServiceUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        p = patch("services.execution.schedule_service.hatchet")
        self.hatchet = p.start()
        self.hatchet.cron.create.return_value = MagicMock(metadata=MagicMock(id="cron-xyz"))
        self.addCleanup(p.stop)
        bt = patch("services.execution.schedule_service.BackgroundTierService")
        self.bg_cls = bt.start()
        self.addCleanup(bt.stop)

    def test_update_concurrency_limit_republishes(self) -> None:
        svc = _service()
        existing = _schedule_row(id=3)
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        svc.update_schedule(3, WorkflowScheduleUpdate(concurrency_limit=4), user_id=7)
        self.bg_cls.return_value.publish.assert_called_once()
        self.assertEqual(self.bg_cls.return_value.publish.call_args[0][1].concurrency_limit, 4)

    def test_update_without_concurrency_does_not_publish(self) -> None:
        svc = _service()
        existing = _schedule_row(id=3)
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        svc.update_schedule(3, WorkflowScheduleUpdate(name="renamed"), user_id=7)
        self.bg_cls.return_value.publish.assert_not_called()

    # --- all-or-nothing registration (C1-05) ---------------------------------

    def test_create_with_hatchet_down_leaves_no_row(self) -> None:
        self.hatchet.cron.create.side_effect = RuntimeError("hatchet down")
        svc = _service()
        row = _schedule_row()
        svc.repo.create.return_value = row
        with self.assertRaises(HTTPException):
            svc.create_schedule(
                WorkflowScheduleCreate(
                    workflow_id=10,
                    name="Site A",
                    schedule_type="cron",
                    cron_expression="0 8 * * *",
                    enabled=True,
                    run_inputs={},
                    concurrency_limit=1,
                ),
                user_id=7,
            )
        # Stored disabled first, and removed again when registration failed.
        self.assertFalse(svc.repo.create.call_args.kwargs["enabled"])
        svc.repo.delete.assert_called_once_with(row)

    def test_update_with_hatchet_down_disables_the_schedule_and_removes_old_entry(self) -> None:
        self.hatchet.cron.create.side_effect = RuntimeError("hatchet down")
        svc = _service()
        existing = _schedule_row(id=3, hatchet_cron_id="old-cron")
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        with self.assertRaises(HTTPException):
            svc.update_schedule(3, WorkflowScheduleUpdate(cron_expression="0 9 * * *"), user_id=7)
        disable_calls = [
            c for c in svc.repo.update.call_args_list if c.kwargs.get("enabled") is False
        ]
        self.assertEqual(len(disable_calls), 1)
        self.hatchet.cron.delete.assert_called_once_with("old-cron")

    # --- a failed registration undoes the publish it caused (O4-04) -------------

    def _create(self, svc: ScheduleService) -> None:
        svc.create_schedule(
            WorkflowScheduleCreate(
                workflow_id=10,
                name="Site A",
                schedule_type="cron",
                cron_expression="0 8 * * *",
                enabled=True,
                run_inputs={},
                concurrency_limit=1,
            ),
            user_id=7,
        )

    def test_failed_create_unpublishes_a_tier_it_created(self) -> None:
        self.hatchet.cron.create.side_effect = RuntimeError("hatchet down")
        svc = _service()
        svc.tier_repo.get_by_workflow_id.return_value = None  # not published before
        svc.repo.create.return_value = _schedule_row()
        with self.assertRaises(HTTPException):
            self._create(svc)
        self.bg_cls.return_value.unpublish_for_workflow_unchecked.assert_called_once_with(10)

    def test_failed_create_keeps_a_tier_that_already_existed(self) -> None:
        self.hatchet.cron.create.side_effect = RuntimeError("hatchet down")
        svc = _service()
        svc.tier_repo.get_by_workflow_id.return_value = MagicMock(concurrency_limit=1)
        svc.repo.create.return_value = _schedule_row()
        with self.assertRaises(HTTPException):
            self._create(svc)
        self.bg_cls.return_value.unpublish_for_workflow_unchecked.assert_not_called()
        self.assertEqual(self.bg_cls.return_value.publish.call_count, 1)  # limit unchanged

    def test_failed_create_restores_the_previous_concurrency_limit(self) -> None:
        self.hatchet.cron.create.side_effect = RuntimeError("hatchet down")
        svc = _service()
        svc.tier_repo.get_by_workflow_id.return_value = MagicMock(concurrency_limit=5)
        svc.repo.create.return_value = _schedule_row()
        with self.assertRaises(HTTPException):
            self._create(svc)  # asks for limit 1
        publishes = self.bg_cls.return_value.publish.call_args_list
        limits = [c[0][1].concurrency_limit for c in publishes]
        self.assertEqual(limits, [1, 5])

    def test_successful_create_keeps_the_tier(self) -> None:
        svc = _service()
        svc.tier_repo.get_by_workflow_id.return_value = None
        svc.repo.create.return_value = _schedule_row()
        self._create(svc)
        self.bg_cls.return_value.unpublish_for_workflow_unchecked.assert_not_called()

    def test_failed_update_unpublishes_a_tier_it_created(self) -> None:
        self.hatchet.cron.create.side_effect = RuntimeError("hatchet down")
        svc = _service()
        svc.tier_repo.get_by_workflow_id.return_value = None
        existing = _schedule_row(id=3)
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        with self.assertRaises(HTTPException):
            svc.update_schedule(3, WorkflowScheduleUpdate(concurrency_limit=4), user_id=7)
        self.bg_cls.return_value.unpublish_for_workflow_unchecked.assert_called_once_with(10)

    def test_failed_update_restores_the_previous_concurrency_limit(self) -> None:
        self.hatchet.cron.create.side_effect = RuntimeError("hatchet down")
        svc = _service()
        svc.tier_repo.get_by_workflow_id.return_value = MagicMock(concurrency_limit=2)
        existing = _schedule_row(id=3)
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        with self.assertRaises(HTTPException):
            svc.update_schedule(3, WorkflowScheduleUpdate(concurrency_limit=4), user_id=7)
        publishes = self.bg_cls.return_value.publish.call_args_list
        limits = [c[0][1].concurrency_limit for c in publishes]
        self.assertEqual(limits, [4, 2])

    # --- an unreachable engine is a 503, not a generic 500 (O4-09) ----------------

    def test_create_with_engine_unreachable_answers_503(self) -> None:
        self.hatchet.cron.create.side_effect = RestConnectionError("connection refused")
        svc = _service()
        svc.repo.create.return_value = _schedule_row()
        with self.assertRaises(HTTPException) as caught:
            self._create(svc)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.detail["message"], ENGINE_UNAVAILABLE_MESSAGE)
        svc.repo.delete.assert_called_once()  # still all-or-nothing

    def test_create_with_engine_5xx_answers_503(self) -> None:
        self.hatchet.cron.create.side_effect = ServiceException(status=503, reason="Unavailable")
        svc = _service()
        svc.repo.create.return_value = _schedule_row()
        with self.assertRaises(HTTPException) as caught:
            self._create(svc)
        self.assertEqual(caught.exception.status_code, 503)

    def test_create_with_engine_rejecting_the_request_stays_500(self) -> None:
        self.hatchet.cron.create.side_effect = ApiException(status=400, reason="Bad Request")
        svc = _service()
        svc.repo.create.return_value = _schedule_row()
        with self.assertRaises(HTTPException) as caught:
            self._create(svc)
        self.assertEqual(caught.exception.status_code, 500)

    def test_create_with_sdk_validation_error_hides_library_internals(self) -> None:
        from pydantic import BaseModel, Field, ValidationError

        class _Probe(BaseModel):
            tenant: str = Field(min_length=36)

        try:
            _Probe(tenant="pwtest")
        except ValidationError as exc:
            self.hatchet.cron.create.side_effect = exc
        svc = _service()
        svc.repo.create.return_value = _schedule_row()
        with self.assertRaises(ValidationFailedError) as caught:
            self._create(svc)
        message = str(caught.exception)
        self.assertIn("Invalid schedule configuration", message)
        for leak in ("pydantic", "input_value", "errors.pydantic.dev", "string_too_short"):
            self.assertNotIn(leak, message)
        svc.repo.delete.assert_called_once()  # still all-or-nothing

    def test_update_with_engine_unreachable_answers_503(self) -> None:
        self.hatchet.cron.create.side_effect = RestTimeoutError("timed out")
        svc = _service()
        existing = _schedule_row(id=3)
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        with self.assertRaises(HTTPException) as caught:
            svc.update_schedule(3, WorkflowScheduleUpdate(cron_expression="0 9 * * *"), user_id=7)
        self.assertEqual(caught.exception.status_code, 503)

    def test_update_registers_new_entry_before_deleting_old(self) -> None:
        order: list[str] = []
        self.hatchet.cron.create.side_effect = lambda **_k: (
            order.append("create"),
            MagicMock(metadata=MagicMock(id="new-cron")),
        )[1]
        self.hatchet.cron.delete.side_effect = lambda _id: order.append("delete")
        svc = _service()
        existing = _schedule_row(id=3, hatchet_cron_id="old-cron")
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        svc.update_schedule(3, WorkflowScheduleUpdate(cron_expression="0 9 * * *"), user_id=7)
        self.assertEqual(order, ["create", "delete"])
        name = self.hatchet.cron.create.call_args.kwargs["cron_name"]
        self.assertTrue(name.startswith("workflow-10-schedule-3-"))

    # --- a fired one-time schedule stays editable (C1-13) ----------------------

    def test_rename_of_fired_one_time_schedule_is_allowed(self) -> None:
        svc = _service()
        past = datetime.now(UTC) - timedelta(days=1)
        existing = _schedule_row(
            id=3, schedule_type="once", cron_expression=None, run_at=past, enabled=False
        )
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        svc.update_schedule(3, WorkflowScheduleUpdate(name="renamed"), user_id=7)
        self.assertEqual(svc.repo.update.call_args.kwargs["name"], "renamed")

    def test_reenabling_a_fired_one_time_schedule_needs_a_future_run_at(self) -> None:
        svc = _service()
        past = datetime.now(UTC) - timedelta(days=1)
        existing = _schedule_row(
            id=3, schedule_type="once", cron_expression=None, run_at=past, enabled=False
        )
        svc.repo.get_by_id.return_value = existing
        with self.assertRaises(ValidationFailedError):
            svc.update_schedule(3, WorkflowScheduleUpdate(enabled=True), user_id=7)


if __name__ == "__main__":
    unittest.main()


class ScheduleRunNowTests(unittest.TestCase):
    def _svc(self, schedule=None):
        svc = _service()
        svc.repo.get_by_id.return_value = schedule if schedule is not None else _schedule_row()
        return svc

    def _run(self, status="pending", **over):
        run = MagicMock()
        run.id = over.get("id", 99)
        run.status = status
        run.error_message = over.get("error_message")
        return run

    def test_starts_run_as_clicking_user_without_marking_fired(self) -> None:
        svc = self._svc(_schedule_row(created_by_id=7, enabled=False))
        registry = MagicMock()
        with patch(
            "services.execution.schedule_service.start_scheduled_run", return_value=self._run()
        ) as start:
            result = svc.run_now(schedule_id=3, user_id=7, plugin_registry_service=registry)

        assert result.run_id == 99
        assert result.status == "pending"
        _, kwargs = start.call_args
        assert kwargs["acting_user_id"] == 7
        # The interactive path goes through the dispatch breaker; the cron worker does not.
        assert kwargs["use_dispatch_breaker"] is True
        assert kwargs["plugin_registry_service"] is registry
        # A manual start is not a fire: the schedule row is never touched.
        svc.repo.mark_triggered.assert_not_called()
        svc.repo.update.assert_not_called()

    def test_failed_run_reports_status_and_message(self) -> None:
        svc = self._svc()
        failed = self._run(status="failed", error_message="Workflow execution engine unavailable")
        with patch("services.execution.schedule_service.start_scheduled_run", return_value=failed):
            result = svc.run_now(schedule_id=3, user_id=7, plugin_registry_service=MagicMock())
        assert result.status == "failed"
        assert result.error_message == "Workflow execution engine unavailable"

    def test_unknown_schedule_is_404(self) -> None:
        svc = _service()
        svc.repo.get_by_id.return_value = None
        with self.assertRaises(NotFoundError):
            svc.run_now(schedule_id=3, user_id=7, plugin_registry_service=MagicMock())

    def test_private_workflow_of_someone_else_is_denied(self) -> None:
        svc = self._svc()
        svc.wf_repo.get_by_id.return_value = (_workflow(visibility="private", creator_id=1), None)
        with patch("services.execution.schedule_service.start_scheduled_run") as start:
            with self.assertRaises(AccessDeniedError):
                svc.run_now(schedule_id=3, user_id=42, plugin_registry_service=MagicMock())
        start.assert_not_called()

    def test_other_users_schedule_is_denied(self) -> None:
        # The stored run inputs include the creator's sealed secrets: only the creator (or an
        # administrator) may replay them.
        svc = self._svc(_schedule_row(created_by_id=7))
        with (
            patch("services.auth.rbac_service.RBACService.has_role", return_value=False),
            patch("services.execution.schedule_service.start_scheduled_run") as start,
        ):
            with self.assertRaises(AccessDeniedError):
                svc.run_now(schedule_id=3, user_id=42, plugin_registry_service=MagicMock())
        start.assert_not_called()

    def test_administrator_may_run_another_users_schedule(self) -> None:
        svc = self._svc(_schedule_row(created_by_id=7))
        with (
            patch("services.auth.rbac_service.RBACService.has_role", return_value=True),
            patch(
                "services.execution.schedule_service.start_scheduled_run",
                return_value=self._run(),
            ) as start,
        ):
            svc.run_now(schedule_id=3, user_id=42, plugin_registry_service=MagicMock())
        assert start.call_args.kwargs["acting_user_id"] == 42
