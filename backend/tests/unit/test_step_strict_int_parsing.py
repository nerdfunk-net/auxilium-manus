"""Whole-number config values go through ``parse_int_flag`` (P-A, W11-07 / W1-04 / W2-08 / W10-05).

``int(raw)`` reads ``True`` as 1 and ``7.9`` as 7; ``parse_int_flag`` refuses both and names the
step and the key. One parametrised pass over the sites that used to do their own ``int()``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.unit._step_helpers import make_context, make_device
from workflow_steps.common.device_file_upload import parse_socket_timeout
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag
from workflow_steps.contact_the_ai.executor import _bounded_int
from workflow_steps.generate_password.executor import _parse_config as generate_password
from workflow_steps.run_catalyst_center_command.executor import _parse_timeout
from workflow_steps.secret_generate.executor import _parse_config as secret_generate
from workflow_steps.secret_get.executor import _parse_config as secret_get
from workflow_steps.start_workflow.executor import _parse_workflow_id

_SECRET = {"connection_id": 1}

# (id, parse(raw) -> Any) : a value of ``raw`` for the one key the site reads
_SITES: list[tuple[str, Callable[[Any], Any]]] = [
    (
        "read_timeout",
        lambda raw: parse_read_timeout({"read_timeout": raw}, step_id="s", default=30),
    ),
    ("socket_timeout", lambda raw: parse_socket_timeout({"socket_timeout": raw}, step_id="s")),
    ("secret-get version", lambda raw: secret_get({**_SECRET, "version": raw})),
    ("secret-generate length", lambda raw: secret_generate({**_SECRET, "length": raw})),
    ("generate-password length", lambda raw: generate_password({"length": raw})),
    ("contact-the-ai max", lambda raw: _bounded_int(raw, 5, 10, "max_tokens")),
    ("start-workflow workflow_id", lambda raw: _parse_workflow_id({"workflow_id": raw})),
    ("run-catalyst-center-command timeout", _parse_timeout),
]
_IDS = [name for name, _ in _SITES]
_PARSERS = [parse for _, parse in _SITES]


@pytest.mark.parametrize("parse", _PARSERS, ids=_IDS)
@pytest.mark.parametrize("raw", [True, 7.9, "abc"])
def test_a_bool_a_fraction_or_text_is_refused(parse: Callable[[Any], Any], raw: Any) -> None:
    with pytest.raises(ValueError):
        parse(raw)


@pytest.mark.parametrize(
    ("parse", "raw"),
    [
        (_PARSERS[0], "45"),
        (_PARSERS[1], 20),
        (_PARSERS[2], "3"),
        (_PARSERS[3], "24"),
        (_PARSERS[4], 20),
        (_PARSERS[5], "4"),
        (_PARSERS[6], "7"),
        (_PARSERS[7], 30),
    ],
    ids=_IDS,
)
def test_a_whole_number_or_its_text_is_accepted(parse: Callable[[Any], Any], raw: Any) -> None:
    parse(raw)


def test_the_message_names_the_step_and_the_key() -> None:
    with pytest.raises(ValueError, match="^s: read_timeout must be a whole number"):
        parse_read_timeout({"read_timeout": 7.9}, step_id="s", default=30)
    with pytest.raises(ValueError, match="^s: read_timeout must be between 5 and 600"):
        parse_read_timeout({"read_timeout": 601}, step_id="s", default=30)


def test_blank_means_the_default() -> None:
    assert parse_read_timeout({"read_timeout": ""}, step_id="s", default=30) == 30
    assert parse_int_flag({"n": None}, "n", default=4) == 4


def test_step_id_prefixes_the_bool_and_int_errors() -> None:
    with pytest.raises(ValueError, match="^step-x: flag must be true or false"):
        parse_bool_flag({"flag": "banana"}, "flag", step_id="step-x")


# ── the four thin git steps ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [True, 7.9, "abc"])
async def test_a_git_step_refuses_a_mangled_repository_id(raw: Any) -> None:
    from workflow_steps.common.git_workflow_step import run_git_workflow_step

    operation = MagicMock()
    outcomes = await run_git_workflow_step(
        config={"git_repository_id": raw},
        context=make_context([make_device("d1")]),
        artifact_service=AsyncMock(),
        node_id="n",
        step_id="git-pull",
        operation=operation,
        operation_name="pull",
    )

    operation.assert_not_called()
    failure = next(o for o in outcomes if o.name == "failure")
    assert "whole number" in str(failure.context.metadata)


@pytest.mark.asyncio
async def test_a_git_step_without_a_repository_id_is_not_configured() -> None:
    from workflow_steps.common.git_workflow_step import run_git_workflow_step

    outcomes = await run_git_workflow_step(
        config={},
        context=make_context([make_device("d1")]),
        artifact_service=AsyncMock(),
        node_id="n",
        step_id="git-pull",
        operation=MagicMock(),
        operation_name="pull",
    )

    assert "not configured" in str(
        next(o for o in outcomes if o.name == "failure").context.metadata
    )
