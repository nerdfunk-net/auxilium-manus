"""DbWorkflowNotesReader: an empty wiki is "" and only a missing permission or workflow is None."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.domain_exceptions import AccessDeniedError, NotFoundError
from services.ai_assistant import workflow_reader as wr


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def patch(monkeypatch, *, allowed=True, result="notes", raises=None):
    monkeypatch.setattr(wr, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(
        wr, "RBACService", lambda db: SimpleNamespace(has_permission=lambda *a: allowed)
    )

    def get_notes(self, workflow_id, user_id):
        if raises:
            raise raises
        return result

    monkeypatch.setattr(
        wr, "WorkflowService", lambda db: SimpleNamespace(get_notes=get_notes.__get__(None))
    )
    monkeypatch.setattr(
        wr,
        "WorkflowService",
        lambda db: SimpleNamespace(get_notes=lambda wid, uid: get_notes(None, wid, uid)),
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"result": "hello"}, "hello"),
        ({"result": None}, ""),
        ({"result": ""}, ""),
        ({"allowed": False}, None),
        ({"raises": NotFoundError("x")}, None),
        ({"raises": AccessDeniedError("x")}, None),
    ],
)
def test_read_notes(monkeypatch, kwargs, expected):
    patch(monkeypatch, **kwargs)
    assert wr.DbWorkflowNotesReader(1).read_notes_sync(5) == expected
