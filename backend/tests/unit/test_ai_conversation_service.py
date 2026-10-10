"""Saved AI conversations: owner isolation, redaction on save, caps, retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.ai_conversations import AiConversation
from core.models.base import Base
from core.models.users import User
from models.ai_conversations import (
    MAX_CONVERSATIONS_PER_USER,
    AiConversationCreate,
    AiConversationUpdate,
    StoredMessage,
)
from services.ai_assistant.conversation_service import AiConversationService
from services.ai_assistant.exceptions import (
    AiConversationLimitError,
    AiConversationNotFoundError,
    AiConversationTooLargeError,
)

CISCO_SECRET = "enable secret 5 $1$abcd$HASHEDVALUE123"


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[User.__table__, AiConversation.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def service(db: Session) -> AiConversationService:
    return AiConversationService.from_session(db)


def _create(
    surface: str = "workflow_editor", subject: str = "12", *messages: StoredMessage, **kw
) -> AiConversationCreate:
    return AiConversationCreate(
        surface=surface,  # type: ignore[arg-type]
        subject_key=subject,
        messages=list(messages)
        or [
            StoredMessage(role="user", content="Add a backup step"),
            StoredMessage(role="assistant", content="Done"),
        ],
        **kw,
    )


def test_create_and_get_roundtrip_with_default_title(service: AiConversationService) -> None:
    created = service.create(1, _create())

    assert created.title == "Add a backup step"
    assert created.message_count == 2
    loaded = service.get(1, created.id)
    assert [m.content for m in loaded.messages] == ["Add a backup step", "Done"]


def test_other_users_conversation_is_not_found(service: AiConversationService) -> None:
    created = service.create(1, _create())

    with pytest.raises(AiConversationNotFoundError):
        service.get(2, created.id)
    with pytest.raises(AiConversationNotFoundError):
        service.update(2, created.id, AiConversationUpdate(title="x"))
    with pytest.raises(AiConversationNotFoundError):
        service.delete(2, created.id)
    assert service.list(2, surface=None, subject_key=None) == []
    assert service.get(1, created.id).id == created.id


def test_list_filters_by_surface_and_subject(service: AiConversationService) -> None:
    service.create(1, _create("workflow_editor", "12"))
    service.create(1, _create("workflow_editor", "13"))
    service.create(1, _create("template_editor", "12"))

    assert len(service.list(1, surface=None, subject_key=None)) == 3
    assert len(service.list(1, surface="workflow_editor", subject_key=None)) == 2
    only = service.list(1, surface="workflow_editor", subject_key="12")
    assert [(c.surface, c.subject_key) for c in only] == [("workflow_editor", "12")]


def test_secrets_are_redacted_before_storage(service: AiConversationService, db: Session) -> None:
    created = service.create(
        1,
        _create(
            "run_viewer",
            "",
            StoredMessage(role="user", content=f"why does this fail?\n{CISCO_SECRET}"),
            StoredMessage(
                role="assistant",
                content="see it",
                error=f"failed: {CISCO_SECRET}",
                proposal={"kind": "template", "summary": f"adds {CISCO_SECRET}"},  # type: ignore[arg-type]
            ),
            title=f"chat {CISCO_SECRET}",
        ),
    )

    raw = db.get(AiConversation, created.id)
    assert raw is not None
    stored = repr(raw.messages) + raw.title
    assert "HASHEDVALUE123" not in stored


def test_proposal_keeps_only_kind_and_summary(service: AiConversationService) -> None:
    with pytest.raises(ValueError):
        StoredMessage.model_validate(
            {
                "role": "assistant",
                "content": "x",
                "proposal": {"kind": "template", "summary": "s", "content": "full body"},
            }
        )


def test_resave_updates_messages_and_title(service: AiConversationService) -> None:
    created = service.create(1, _create())

    updated = service.update(
        1,
        created.id,
        AiConversationUpdate(
            title="Renamed",
            messages=[
                StoredMessage(role="user", content="one"),
                StoredMessage(role="user", content="two"),
            ],
        ),
    )

    assert updated.title == "Renamed"
    assert [m.content for m in updated.messages] == ["one", "two"]


def test_oversized_conversation_is_refused(service: AiConversationService) -> None:
    big = "x" * 19000
    messages = [StoredMessage(role="user", content=big) for _ in range(12)]

    with pytest.raises(AiConversationTooLargeError):
        service.create(1, _create("inventory", "", *messages))


def test_per_user_limit(service: AiConversationService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("services.ai_assistant.conversation_service.MAX_CONVERSATIONS_PER_USER", 2)
    service.create(1, _create())
    service.create(1, _create())
    with pytest.raises(AiConversationLimitError):
        service.create(1, _create())
    # Another user is unaffected.
    service.create(2, _create())
    assert MAX_CONVERSATIONS_PER_USER >= 1


def test_delete_removes_the_row(service: AiConversationService) -> None:
    created = service.create(1, _create())
    service.delete(1, created.id)
    with pytest.raises(AiConversationNotFoundError):
        service.get(1, created.id)


def test_retention_purges_only_stale_rows(service: AiConversationService, db: Session) -> None:
    old = service.create(1, _create())
    fresh = service.create(1, _create())
    db.execute(
        update(AiConversation)
        .where(AiConversation.id == old.id)
        .values(updated_at=datetime.now(UTC) - timedelta(days=100))
    )
    db.commit()

    assert service.purge_older_than_days(0) == 0
    assert service.purge_older_than_days(90) == 1
    assert service.get(1, fresh.id).id == fresh.id
    with pytest.raises(AiConversationNotFoundError):
        service.get(1, old.id)
