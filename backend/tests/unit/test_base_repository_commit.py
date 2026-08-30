"""BaseRepository.create/update/delete must commit when given a caller-owned
(request-scoped) session, not just flush.

core.database.get_db() never calls commit() itself — it only yields the
session and closes it in a finally block. A flush-only write is visible
within the same transaction (so the same request's response looks correct)
but is rolled back on session.close(), silently discarding the row before
any later request can see it. Reproduced here with two separate sessions
against a real SQLite DB (mocks would hide this class of bug entirely,
since a mock session's flush()/commit() are both no-ops).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.base import Base
from core.models.git import GitRepository
from repositories.git.git_repository_repository import GitRepositoryRepository


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[GitRepository.__table__])
    try:
        yield sessionmaker(autocommit=False, autoflush=False, bind=engine)
    finally:
        engine.dispose()


def test_create_with_external_session_survives_session_close(session_factory) -> None:
    repo = GitRepositoryRepository()

    session_a = session_factory()
    created = repo.create(
        db=session_a,
        name="workflow-version-control",
        category="workflows",
        url="https://example.com/repo.git",
        branch="main",
    )
    created_id = created.id
    session_a.close()

    session_b = session_factory()
    found = repo.get_by_id(created_id, db=session_b)
    session_b.close()

    assert found is not None
    assert found.name == "workflow-version-control"


def test_update_with_external_session_survives_session_close(session_factory) -> None:
    repo = GitRepositoryRepository()

    session_a = session_factory()
    created = repo.create(
        db=session_a,
        name="original-name",
        category="workflows",
        url="https://example.com/repo.git",
        branch="main",
    )
    created_id = created.id
    repo.update(created_id, db=session_a, name="renamed")
    session_a.close()

    session_b = session_factory()
    found = repo.get_by_id(created_id, db=session_b)
    session_b.close()

    assert found is not None
    assert found.name == "renamed"


def test_delete_with_external_session_survives_session_close(session_factory) -> None:
    repo = GitRepositoryRepository()

    session_a = session_factory()
    created = repo.create(
        db=session_a,
        name="to-be-deleted",
        category="workflows",
        url="https://example.com/repo.git",
        branch="main",
    )
    created_id = created.id
    repo.delete(created_id, db=session_a)
    session_a.close()

    session_b = session_factory()
    found = repo.get_by_id(created_id, db=session_b)
    session_b.close()

    assert found is None
