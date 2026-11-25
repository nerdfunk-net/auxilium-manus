"""``resolve_workflow_user_id``: the service user the contact-the-ai step runs as (W10-12)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.ai_assistant.workflow_user import WorkflowAiUserError, resolve_workflow_user_id

REPO = "services.ai_assistant.workflow_user.UserRepository"


def test_an_unset_user_name_is_refused_without_a_lookup() -> None:
    with patch(REPO) as repo, pytest.raises(WorkflowAiUserError) as caught:
        resolve_workflow_user_id(MagicMock(), None)
    assert caught.value.reason == "not_set"
    repo.assert_not_called()


@pytest.mark.parametrize("found", [None, SimpleNamespace(id=3, is_active=False)])
def test_an_unknown_or_inactive_user_is_refused(found) -> None:
    with patch(REPO) as repo, pytest.raises(WorkflowAiUserError) as caught:
        repo.return_value.get_by_username_ci.return_value = found
        resolve_workflow_user_id(MagicMock(), "AI-Service")
    assert caught.value.reason == "not_active"


def test_an_active_user_is_found_case_insensitively_and_its_id_returned() -> None:
    db = MagicMock()
    with patch(REPO) as repo:
        repo.return_value.get_by_username_ci.return_value = SimpleNamespace(id=7, is_active=True)
        assert resolve_workflow_user_id(db, "AI-Service") == 7
    repo.assert_called_once_with(db)
    repo.return_value.get_by_username_ci.assert_called_once_with("AI-Service")
