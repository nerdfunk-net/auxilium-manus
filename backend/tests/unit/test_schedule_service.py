"""Tests for services/execution/schedule_service.py."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from core.domain_exceptions import AccessDeniedError, NotFoundError, ValidationFailedError
from models.schedules import WorkflowScheduleCreate, WorkflowScheduleUpdate
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
        self.assertEqual(
            self.bg_cls.return_value.publish.call_args[0][1].concurrency_limit, 4
        )

    def test_update_without_concurrency_does_not_publish(self) -> None:
        svc = _service()
        existing = _schedule_row(id=3)
        svc.repo.get_by_id.return_value = existing
        svc.repo.update.return_value = existing
        svc.update_schedule(3, WorkflowScheduleUpdate(name="renamed"), user_id=7)
        self.bg_cls.return_value.publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
