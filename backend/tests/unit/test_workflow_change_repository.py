"""Repository-level coverage for workflow_changes: creation, ordering, and the
get_latest_commit_sha lookup used to chain parent_commit_sha across saves."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.workflow_changes import WorkflowChange
from repositories.workflow_change_repository import WorkflowChangeRepository


class WorkflowChangeRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine, tables=[WorkflowChange.__table__])
        self.addCleanup(engine.dispose)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()
        self.addCleanup(self.db.close)
        self.repo = WorkflowChangeRepository(self.db)

    def test_create_persists_all_fields(self) -> None:
        change = self.repo.create(
            workflow_id=1,
            actor_id=7,
            actor_username="alice",
            action="created",
            commit_sha="abc123",
            parent_commit_sha=None,
        )

        self.assertIsNotNone(change.id)
        self.assertEqual(change.workflow_id, 1)
        self.assertEqual(change.actor_id, 7)
        self.assertEqual(change.actor_username, "alice")
        self.assertEqual(change.action, "created")
        self.assertEqual(change.commit_sha, "abc123")
        self.assertIsNone(change.parent_commit_sha)
        self.assertIsNotNone(change.created_at)

    def test_list_by_workflow_orders_newest_first_and_scopes_to_workflow(self) -> None:
        self.repo.create(
            workflow_id=1,
            actor_id=1,
            actor_username="alice",
            action="created",
            commit_sha="c1",
            parent_commit_sha=None,
        )
        self.repo.create(
            workflow_id=1,
            actor_id=1,
            actor_username="alice",
            action="updated",
            commit_sha="c2",
            parent_commit_sha="c1",
        )
        self.repo.create(
            workflow_id=2,
            actor_id=1,
            actor_username="alice",
            action="created",
            commit_sha="other",
            parent_commit_sha=None,
        )

        rows = self.repo.list_by_workflow(1)

        self.assertEqual([r.commit_sha for r in rows], ["c2", "c1"])

    def test_get_latest_commit_sha_ignores_null_commits_and_other_workflows(self) -> None:
        self.repo.create(
            workflow_id=1,
            actor_id=1,
            actor_username="alice",
            action="created",
            commit_sha="c1",
            parent_commit_sha=None,
        )
        # A later, non-versioned save has no commit — must not shadow c1.
        self.repo.create(
            workflow_id=1,
            actor_id=1,
            actor_username="alice",
            action="updated",
            commit_sha=None,
            parent_commit_sha=None,
        )
        self.repo.create(
            workflow_id=2,
            actor_id=1,
            actor_username="alice",
            action="created",
            commit_sha="other-workflow",
            parent_commit_sha=None,
        )

        self.assertEqual(self.repo.get_latest_commit_sha(1), "c1")

    def test_get_latest_commit_sha_returns_none_when_no_commits_exist(self) -> None:
        self.assertIsNone(self.repo.get_latest_commit_sha(1))


if __name__ == "__main__":
    unittest.main()
