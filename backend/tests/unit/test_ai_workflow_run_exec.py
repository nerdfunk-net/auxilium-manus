"""WorkflowRunExecutor: the token decides what starts; nothing else does."""

from __future__ import annotations

import asyncio

import pytest

from services.ai_assistant.released_run_builder import ProposedDevice
from services.ai_assistant.workflow_run_exec import WorkflowRunExecutor
from services.ai_assistant.workflow_run_token import InvalidRunTokenError, issue_run_token


class _Reader:
    def __init__(self) -> None:
        self.started: list[tuple] = []

    async def start(self, workflow_id, **kwargs):
        self.started.append((workflow_id, kwargs))
        return 77


def test_starts_exactly_what_the_token_holds() -> None:
    reader = _Reader()
    dev = ProposedDevice(ip="10.0.0.1", name="sw1")
    token, _ = issue_run_token(
        user_id=4, workflow_id=5, run_inputs={"features": "ospf"}, devices=[dev], stamp="st"
    )

    started = asyncio.run(
        WorkflowRunExecutor(reader).execute(
            user_id=4, token=token, credentials={"cred": "lab"}, free_ip_driver="cisco_ios"
        )
    )

    assert (started.run_id, started.workflow_id) == (77, 5)
    assert len(reader.started[0][1]["token_id"]) == 32
    assert reader.started == [
        (
            5,
            {
                "model_inputs": {"features": "ospf"},
                "devices": [dev],
                "credentials": {"cred": "lab"},
                "free_ip_driver": "cisco_ios",
                "release_stamp": "st",
                "token_id": reader.started[0][1]["token_id"],
            },
        )
    ]


def test_another_users_token_starts_nothing() -> None:
    reader = _Reader()
    token, _ = issue_run_token(user_id=4, workflow_id=5, run_inputs={}, devices=[], stamp="st")

    with pytest.raises(InvalidRunTokenError):
        asyncio.run(WorkflowRunExecutor(reader).execute(user_id=9, token=token))

    assert reader.started == []
