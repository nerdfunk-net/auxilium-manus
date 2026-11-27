"""Safety net for the shared source helpers a refactoring moves (P-T, W13-12).

``agent_source`` (36 %), ``git_yaml_source`` (29 %) and ``retry_config`` (68 %) were the least
covered ``common/`` modules; ``resolve_source`` (P-D) and the parser sweep (P-A) touch them.
"""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from services.agents.source_config_service import AgentSourceNotFoundError
from workflow_steps.common.agent_source import resolve_agent_connection
from workflow_steps.common.retry_config import (
    MAX_RETRY_ATTEMPTS,
    parse_retry_backoff_seconds,
)
from workflow_steps.set_default_attributes import git_source as git_yaml_source

# ── agent_source ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("source_id", ["", "   ", None])
def test_an_empty_agent_source_is_a_config_error(source_id: Any) -> None:
    with pytest.raises(ValueError, match="s: agent_source_id is not configured"):
        resolve_agent_connection(MagicMock(), source_id, step_id="s")


def test_an_unknown_agent_source_becomes_a_value_error_with_the_step_id() -> None:
    with patch("workflow_steps.common.agent_source.AgentSourceConfigService") as service:
        service.return_value.resolve_connection.side_effect = AgentSourceNotFoundError("agent x")

        with pytest.raises(ValueError, match="^s: "):
            resolve_agent_connection(MagicMock(), "x", step_id="s")


def test_the_agent_source_id_is_trimmed_before_the_lookup() -> None:
    with patch("workflow_steps.common.agent_source.AgentSourceConfigService") as service:
        connection = resolve_agent_connection(MagicMock(), "  a1 ", step_id="s")

    service.return_value.resolve_connection.assert_called_once_with("a1")
    assert connection is service.return_value.resolve_connection.return_value


# ── git_yaml_source ────────────────────────────────────────────────────────────────────────────


def _load(tmp_path: Path, **kwargs: Any) -> Any:
    repository = {"id": 3, "name": "defaults"}
    with (
        patch.object(git_yaml_source, "load_git_repository", return_value=repository),
        patch.object(git_yaml_source, "git_checkout", return_value=nullcontext(tmp_path)),
    ):
        return git_yaml_source.load_yaml_from_git_source(
            **{"git_repository_id": 3, "filename_pattern": "*.yaml", "step_id": "s", **kwargs}
        )


def test_the_one_matching_yaml_file_is_parsed(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text("site: ber\nvlan: 10\n")
    (tmp_path / "notes.txt").write_text("not yaml\n")

    assert _load(tmp_path) == {"site": "ber", "vlan": 10}


def test_several_matching_files_are_an_error_naming_them(tmp_path: Path) -> None:
    """W4-11: the step no longer reads the alphabetically first of several matches."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "b.yaml").write_text("x: 1\n")
    (tmp_path / "sub" / "a.yaml").write_text("x: 2\n")

    with pytest.raises(ValueError) as caught:
        _load(tmp_path)

    message = str(caught.value)
    assert message.startswith("s: 2 files match '*.yaml' in git repository 'defaults'")
    assert "b.yaml, sub/a.yaml" in message
    assert str(tmp_path) not in message
    assert "exactly one" in message


def test_the_named_files_are_capped(tmp_path: Path) -> None:
    for index in range(7):
        (tmp_path / f"f{index}.yaml").write_text("x: 1\n")

    with pytest.raises(ValueError, match=r"7 files match .*f4\.yaml, \.\.\.\)") as caught:
        _load(tmp_path)

    assert "f5.yaml" not in str(caught.value)


def test_the_directory_narrows_the_search(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.yaml").write_text("x: 1\n")
    (tmp_path / "a.yaml").write_text("x: 2\n")

    assert _load(tmp_path, directory="sub") == {"x": 1}


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"git_repository_id": None}, "git_repository_id is not configured"),
        ({"filename_pattern": "  "}, "filename_pattern is not configured"),
    ],
)
def test_missing_configuration_is_a_value_error(
    tmp_path: Path, kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _load(tmp_path, **kwargs)


def test_no_matching_file_names_the_repository(tmp_path: Path) -> None:
    with pytest.raises(
        ValueError, match="no file matching '\\*.yaml' found in git repository 'defaults'"
    ):
        _load(tmp_path)


def test_invalid_yaml_is_a_value_error_with_the_file_name(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("a: [unclosed\n")

    with pytest.raises(ValueError, match="invalid YAML in 'bad.yaml'"):
        _load(tmp_path)


# ── retry_config ───────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [None, [], "", "  "])
def test_no_retry_by_default(raw: Any) -> None:
    assert (
        parse_retry_backoff_seconds({"retry_backoff_seconds": raw}, step_id="s").backoff_seconds
        == ()
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [([5, "10"], (5, 10)), ("[1, 2, 3]", (1, 2, 3)), ("5\n10\n", (5, 10))],
)
def test_delays_may_be_a_list_json_or_lines(raw: Any, expected: tuple[int, ...]) -> None:
    policy = parse_retry_backoff_seconds({"retry_backoff_seconds": raw}, step_id="s")

    assert policy.backoff_seconds == expected


@pytest.mark.parametrize("raw", [{"a": 1}, 5, ["x"], [None], "a\nb", "7"])
def test_other_shapes_are_refused(raw: Any) -> None:
    with pytest.raises(ValueError, match="must be a list of integers"):
        parse_retry_backoff_seconds({"retry_backoff_seconds": raw}, step_id="s")


def test_at_most_five_attempts() -> None:
    parse_retry_backoff_seconds({"retry_backoff_seconds": [1] * MAX_RETRY_ATTEMPTS}, step_id="s")

    with pytest.raises(ValueError, match="more than 5 entries"):
        parse_retry_backoff_seconds(
            {"retry_backoff_seconds": [1] * (MAX_RETRY_ATTEMPTS + 1)}, step_id="s"
        )


@pytest.mark.parametrize("delay", [0, -1, 601])
def test_each_delay_is_bounded(delay: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 600"):
        parse_retry_backoff_seconds({"retry_backoff_seconds": [delay]}, step_id="s")


def test_an_invalid_agent_source_becomes_a_value_error_with_the_step_id() -> None:
    # W8-06 leftover: like every other source, a validation error names the step.
    from services.agents.exceptions import AgentValidationError

    with patch("workflow_steps.common.agent_source.AgentSourceConfigService") as service:
        service.return_value.resolve_connection.side_effect = AgentValidationError(
            "An agent source needs a shared-secret credential"
        )

        with pytest.raises(ValueError, match="^s: An agent source needs a shared-secret"):
            resolve_agent_connection(MagicMock(), "x", step_id="s")


def test_resolve_source_can_call_another_resolver() -> None:
    from workflow_steps.common.source_credentials import resolve_source

    service = MagicMock()

    result = resolve_source(
        service, "a", step_id="s", invalid=KeyError, resolve=service.resolve_connection
    )

    service.resolve_connection.assert_called_once_with("a")
    service.resolve_credentials.assert_not_called()
    assert result is service.resolve_connection.return_value
