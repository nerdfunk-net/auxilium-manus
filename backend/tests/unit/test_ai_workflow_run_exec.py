"""WorkflowRunExecutor: the token decides what starts; nothing else does."""

from __future__ import annotations

import asyncio

import pytest

from services.ai_assistant.workflow_run_exec import WorkflowRunExecutor
from services.ai_assistant.workflow_run_token import InvalidRunTokenError, issue_run_token


class _Reader:
    def __init__(self) -> None:
        self.started: list[tuple] = []

    async def start(self, workflow_id, *, run_inputs, device_ids):
        self.started.append((workflow_id, run_inputs, device_ids))
        return 77


def test_starts_exactly_what_the_token_holds() -> None:
    reader = _Reader()
    token, _ = issue_run_token(
        user_id=4, workflow_id=5, run_inputs={"features": "ospf"}, device_ids=["d1"]
    )

    started = asyncio.run(WorkflowRunExecutor(reader).execute(user_id=4, token=token))

    assert (started.run_id, started.workflow_id) == (77, 5)
    assert reader.started == [(5, {"features": "ospf"}, ["d1"])]


def test_another_users_token_starts_nothing() -> None:
    reader = _Reader()
    token, _ = issue_run_token(user_id=4, workflow_id=5, run_inputs={}, device_ids=[])

    with pytest.raises(InvalidRunTokenError):
        asyncio.run(WorkflowRunExecutor(reader).execute(user_id=9, token=token))

    assert reader.started == []
