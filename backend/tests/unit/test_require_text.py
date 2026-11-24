"""``require_text``: one rule and one message for a required, stripped text setting (W9-11)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from models.workflow_context import WorkflowContext
from workflow_steps.common.step_flags import require_text
from workflow_steps.get_from_db.executor import execute as get_from_db
from workflow_steps.notify.executor import execute as notify
from workflow_steps.notify_mattermost.executor import execute as notify_mattermost
from workflow_steps.notify_on_error.executor import execute as notify_on_error
from workflow_steps.send_mail.executor import execute as send_mail
from workflow_steps.store_in_db.executor import execute as store_in_db


def test_returns_the_stripped_text() -> None:
    assert require_text({"k": "  v  "}, "k", step_id="s") == "v"


@pytest.mark.parametrize("config", [{}, {"k": None}, {"k": ""}, {"k": "   "}])
def test_missing_or_blank_text_names_step_and_key(config: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"^s: k is required$"):
        require_text(config, "k", step_id="s")


def test_default_fills_an_unset_or_empty_value() -> None:
    assert require_text({}, "k", step_id="s", default=" d ") == "d"
    assert require_text({"k": ""}, "k", step_id="s", default="d") == "d"
    assert require_text({"k": "x"}, "k", step_id="s", default="d") == "x"


def test_a_whitespace_only_value_does_not_fall_back_to_the_default() -> None:
    with pytest.raises(ValueError, match="s: k is required"):
        require_text({"k": " "}, "k", step_id="s", default="d")


def test_blank_default_is_still_an_error() -> None:
    with pytest.raises(ValueError, match="s: k is required"):
        require_text({}, "k", step_id="s", default="")


_STEPS = [
    ("get-from-db", get_from_db, {"storage_key": "", "destination_path": "x"}, "storage_key"),
    ("get-from-db", get_from_db, {"storage_key": "k", "destination_path": ""}, "destination_path"),
    ("send-mail", send_mail, {"to": "", "subject": "s", "body": "b"}, "to"),
    ("send-mail", send_mail, {"to": "a@b.c", "subject": "", "body": "b"}, "subject"),
    ("send-mail", send_mail, {"to": "a@b.c", "subject": "s", "body": ""}, "body"),
    ("store-in-db", store_in_db, {"storage_key": ""}, "storage_key"),
    (
        "notify-mattermost",
        notify_mattermost,
        {"mattermost_source_id": "", "team_name": "t", "channel_name": "c", "message": "m"},
        "mattermost_source_id",
    ),
    (
        "notify-mattermost",
        notify_mattermost,
        {"mattermost_source_id": "s", "team_name": "", "channel_name": "c", "message": "m"},
        "team_name",
    ),
    (
        "notify-mattermost",
        notify_mattermost,
        {"mattermost_source_id": "s", "team_name": "t", "channel_name": "", "message": "m"},
        "channel_name",
    ),
    (
        "notify-mattermost",
        notify_mattermost,
        {"mattermost_source_id": "s", "team_name": "t", "channel_name": "c", "message": " "},
        "message",
    ),
    (
        "notify-on-error",
        notify_on_error,
        {"notify_mattermost": True, "mattermost_source_id": "", "team_name": "t",
         "channel_name": "c", "message": "m"},
        "mattermost_source_id",
    ),
    (
        "notify-on-error",
        notify_on_error,
        {"notify_mattermost": True, "mattermost_source_id": "s", "team_name": "",
         "channel_name": "c", "message": "m"},
        "team_name",
    ),
    (
        "notify-on-error",
        notify_on_error,
        {"notify_mattermost": True, "mattermost_source_id": "s", "team_name": "t",
         "channel_name": "", "message": "m"},
        "channel_name",
    ),
    ("notify-on-error", notify_on_error, {"message": " "}, "message"),
    ("notify", notify, {"message": " "}, "message"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("step_id", "execute", "config", "key"), _STEPS)
async def test_each_step_reports_the_same_message(
    step_id: str, execute: Any, config: dict[str, Any], key: str
) -> None:
    with pytest.raises(ValueError, match=rf"^{step_id}: {key} is required$"):
        await execute(
            config=config,
            context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="n",
            device_sessions=MagicMock(),
        )


@pytest.mark.parametrize("raw", ["parsed", " out_1 ", "A9_"])
def test_parse_output_key_accepts_names(raw: str) -> None:
    from workflow_steps.common.step_flags import parse_output_key

    assert parse_output_key(raw) == raw.strip()


@pytest.mark.parametrize("raw", [None, "", "  "])
def test_parse_output_key_requires_a_value(raw: object) -> None:
    from workflow_steps.common.step_flags import parse_output_key

    with pytest.raises(ValueError, match="^output_key is required$"):
        parse_output_key(raw)


@pytest.mark.parametrize("raw", ["1abc", "_a", "a-b", "a.b", "a b"])
def test_parse_output_key_refuses_other_names(raw: str) -> None:
    from workflow_steps.common.step_flags import parse_output_key

    with pytest.raises(ValueError, match="must start with a letter"):
        parse_output_key(raw)
