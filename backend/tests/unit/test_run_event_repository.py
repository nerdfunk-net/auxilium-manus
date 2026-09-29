"""RunEventRepository: append-only live events for a run (connect attempts, retries...)."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.runs import WorkflowRun, WorkflowRunEvent
from core.models.users import User
from repositories.run_event_repository import MAX_EVENTS_PER_RUN, RunEventRepository


class RunEventRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        WorkflowRun.metadata.create_all(
            engine, tables=[User.__table__, WorkflowRun.__table__, WorkflowRunEvent.__table__]
        )
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.run_ids: list[int] = []
        for uuid in ("run-1", "run-2"):
            run = WorkflowRun(
                uuid=uuid,
                workflow_id=1,
                triggered_by_id=None,
                status="running",
                trigger_type="manual",
                device_ids=[],
            )
            self.db.add(run)
            self.db.commit()
            self.run_ids.append(run.id)
        self.run_id, self.other_run_id = self.run_ids
        self.repo = RunEventRepository(self.db)

    def _add(self, message: str, **overrides) -> None:
        self.repo.add_event(
            run_id=overrides.pop("run_id", self.run_id),
            step_node_id="a",
            kind=overrides.pop("kind", "connect_attempt"),
            message=message,
            **overrides,
        )

    def test_add_and_list_in_insertion_order_with_all_fields(self) -> None:
        self._add("first", level="info", device_name="r1", child_index=2)
        self._add("second", level="warning", kind="connect_retry")

        events = self.repo.list_events(self.run_id)

        self.assertEqual([e.message for e in events], ["first", "second"])
        self.assertEqual(events[0].device_name, "r1")
        self.assertEqual(events[0].child_index, 2)
        self.assertEqual(events[0].step_node_id, "a")
        self.assertEqual(events[1].level, "warning")
        self.assertEqual(events[1].kind, "connect_retry")
        self.assertIsNotNone(events[0].created_at)

    def test_list_after_id_returns_only_newer_events(self) -> None:
        for i in range(4):
            self._add(f"e{i}")
        events = self.repo.list_events(self.run_id)

        newer = self.repo.list_events(self.run_id, after_id=events[1].id)

        self.assertEqual([e.message for e in newer], ["e2", "e3"])

    def test_list_respects_limit(self) -> None:
        for i in range(5):
            self._add(f"e{i}")

        self.assertEqual(len(self.repo.list_events(self.run_id, limit=2)), 2)

    def test_events_are_scoped_per_run(self) -> None:
        self._add("mine")
        self._add("theirs", run_id=self.other_run_id)

        self.assertEqual([e.message for e in self.repo.list_events(self.run_id)], ["mine"])

    def test_cap_stops_inserts_and_adds_one_truncation_marker(self) -> None:
        for i in range(5):
            self.repo.add_event(
                run_id=self.run_id,
                step_node_id="a",
                kind="connect_attempt",
                message=f"e{i}",
                max_events=3,
            )

        events = self.repo.list_events(self.run_id)

        self.assertEqual([e.message for e in events[:3]], ["e0", "e1", "e2"])
        self.assertEqual(len(events), 4)
        self.assertEqual(events[3].kind, "truncated")

    def test_cap_is_per_run(self) -> None:
        for i in range(3):
            self.repo.add_event(
                run_id=self.run_id, step_node_id="a", kind="k", message=f"e{i}", max_events=3
            )
        self.repo.add_event(
            run_id=self.other_run_id, step_node_id="a", kind="k", message="ok", max_events=3
        )

        self.assertEqual(len(self.repo.list_events(self.other_run_id)), 1)

    def test_default_cap_matches_documented_limit(self) -> None:
        self.assertEqual(MAX_EVENTS_PER_RUN, 2000)

    def test_long_messages_are_truncated(self) -> None:
        self._add("x" * 5000)

        self.assertLessEqual(len(self.repo.list_events(self.run_id)[0].message), 1000)


if __name__ == "__main__":
    unittest.main()
