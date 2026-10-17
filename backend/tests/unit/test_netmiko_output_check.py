"""CF-04 step 1: the closed list of CLI error markers."""

from __future__ import annotations

import re

import pytest

from services.network.netmiko.output_check import (
    CONFIG_ERROR_PATTERN,
    CliError,
    find_cli_error,
    find_commit_error,
)

POSITIVE = [
    ("% Invalid input detected at '^' marker.", "invalid_input"),
    ("% Incomplete command.", "incomplete_command"),
    ("% Ambiguous command:  \"sh\"", "ambiguous_command"),
    ("% Invalid command at '^' marker.", "invalid_input"),
    ("Syntax error while parsing 'foo'", "syntax_error"),
    ("% Invalid input (at token 0: 'foo')", "invalid_input"),
    ("syntax error, expecting <command>.", "syntax_error"),
    ("error: syntax error", "syntax_error"),
    ("Command authorization failed.", "authorization_failed"),
    ("% Unrecognized command found at '^' position.", "unknown_command"),
    ("% Bad IP address and mask", "bad_value"),
]

NEGATIVE = [
    "% Warning: Interface is administratively down",
    "Router(config-if)#description % Invalid input detected",
    "description invalid input from customer",
    "Building configuration...",
    "snmp-server community invalid RO",
    "",
]


@pytest.mark.parametrize(("text", "label"), POSITIVE)
def test_known_refusals_are_detected(text: str, label: str) -> None:
    transcript = f"interface Gi0/1\n{text}\nend"
    error = find_cli_error(transcript)
    assert error == CliError(label, 2)


@pytest.mark.parametrize("text", NEGATIVE)
def test_benign_text_is_not_an_error(text: str) -> None:
    assert find_cli_error(text) is None


@pytest.mark.parametrize(("text", "_label"), POSITIVE)
def test_config_error_pattern_matches_what_find_cli_error_matches(text: str, _label: str) -> None:
    assert re.search(CONFIG_ERROR_PATTERN, text, flags=re.M)


def test_only_labels_leave_the_module() -> None:
    error = find_cli_error("tacacs-server key hunter2\n% Invalid input detected at '^' marker.")
    assert error is not None
    assert "hunter2" not in repr(error)


def test_commit_errors() -> None:
    assert find_commit_error("% Failed to commit one or more configuration items") is not None
    assert find_commit_error("Commit complete.") is None
