"""AiWriteGate: identity, consent row and schedule checks for the AI write path."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.domain_exceptions import AccessDeniedError, ConflictError
from services.workflow.ai_write_gate import AiWriteGate


def _gate(
    *,
    username: str | None = "ai-assistant",
    active: bool = True,
    session: object | None = "session",
    schedules: list[bool] | None = None,
) -> AiWriteGate:
    gate = AiWriteGate(MagicMock())
    gate._users = MagicMock()
    if username is None:
        gate._users.get_by_id.return_value = None
    else:
        user = MagicMock(is_active=active)
        user.username = username
        gate._users.get_by_id.return_value = user
    gate._sessions = MagicMock()
    gate._sessions.get_active_for_workflow.return_value = session
    gate._schedules = MagicMock()
    gate._schedules.list_by_workflow_id.return_value = [
        MagicMock(enabled=enabled) for enabled in (schedules or [])
    ]
    return gate


def test_unknown_user_is_denied() -> None:
    with pytest.raises(AccessDeniedError):
        _gate(username=None).assert_may_write(1, 42, canvas=True)


def test_a_human_user_cannot_use_the_ai_path() -> None:
    with pytest.raises(AccessDeniedError, match="ai-assistant"):
        _gate(username="alice").assert_may_write(1, 42, canvas=True)


def test_inactive_ai_user_is_denied() -> None:
    with pytest.raises(AccessDeniedError, match="disabled"):
        _gate(active=False).assert_may_write(1, 42, canvas=True)


def test_missing_session_is_denied_and_names_the_workflow() -> None:
    with pytest.raises(AccessDeniedError, match="workflow 7"):
        _gate(session=None).assert_may_write(7, 42, canvas=True)


def test_active_session_without_schedules_passes() -> None:
    assert _gate(session="s").assert_may_write(1, 42, canvas=True) == "s"


def test_enabled_schedule_blocks_canvas_writes() -> None:
    with pytest.raises(ConflictError, match="1 enabled schedule"):
        _gate(schedules=[True, False]).assert_may_write(1, 42, canvas=True)


def test_enabled_schedule_does_not_block_notes() -> None:
    assert _gate(schedules=[True]).assert_may_write(1, 42, canvas=False) == "session"


def test_disabled_schedules_do_not_block_canvas_writes() -> None:
    assert _gate(schedules=[False, False]).assert_may_write(1, 42, canvas=True) == "session"
