"""O1-06: deleting a user must not scan every workflow save in ``workflow_changes``.

``actor_id`` is a foreign key with ``ON DELETE SET NULL``; PostgreSQL has to find the referencing
rows, and ``workflow_changes`` gets one row per workflow save.
"""

from __future__ import annotations

from core.models.workflow_changes import WorkflowChange


def test_actor_id_is_indexed() -> None:
    indexed = {
        column.name for index in WorkflowChange.__table__.indexes for column in index.columns
    }
    assert "actor_id" in indexed
