"""``require_session``: the one place a step asks its run for the database session."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from workflow_steps.common.run_session import require_session


def test_returns_the_session_of_the_run() -> None:
    session = MagicMock(name="db")
    with patch("workflow_steps.common.run_session.object_session", return_value=session) as asked:
        run = MagicMock(name="run")
        assert require_session(run, "some-step") is session
    asked.assert_called_once_with(run)


def test_run_without_session_raises_runtime_error_naming_the_step() -> None:
    with patch("workflow_steps.common.run_session.object_session", return_value=None):
        with pytest.raises(
            RuntimeError, match=r"^some-step: WorkflowRun has no active DB session$"
        ):
            require_session(MagicMock(), "some-step")
