"""Mock-device data for replaying already-fetched command output (no genie needed here).

``replay_worker`` runs a Genie Ops class (``learn bgp``) against a Unicon *mock device* that answers
each command with the text the caller already collected, so the shim can build the same ``info``
tree ``pyats learn`` would, without any connection to a device. A command the caller did not
collect is answered with ``% Invalid command``; Genie skips that leaf and learns the rest.

This module only builds the mock data and is importable without genie.
"""

from __future__ import annotations

from typing import Any

import yaml

PROMPT = "R1#"
# What Unicon's IOS-XE connection asks while connecting; the answers are empty on purpose.
_CONNECT_COMMANDS = (
    "term length 0",
    "term width 0",
    "show version | include operating mode",
)
# Genie OS names the replay accepts, and the features it can learn.
ALLOWED_OS = frozenset({"iosxe", "ios"})
ALLOWED_FEATURES = frozenset({"bgp", "ospf"})
MAX_COMMANDS = 32
MAX_OUTPUT_CHARS = 4_000_000


class ReplayInputError(ValueError):
    """The request cannot be replayed; the message is safe to show."""


def validate(os_name: str, feature: str, commands: list[dict[str, str]]) -> None:
    if os_name not in ALLOWED_OS:
        raise ReplayInputError(f"os must be one of {sorted(ALLOWED_OS)}")
    if feature not in ALLOWED_FEATURES:
        raise ReplayInputError(f"feature must be one of {sorted(ALLOWED_FEATURES)}")
    if not commands or len(commands) > MAX_COMMANDS:
        raise ReplayInputError(f"between 1 and {MAX_COMMANDS} commands are required")
    if sum(len(c["output"]) for c in commands) > MAX_OUTPUT_CHARS:
        raise ReplayInputError("the outputs are too large to replay")
    names = [c["command"] for c in commands]
    if len(set(names)) != len(names):
        raise ReplayInputError("a command may appear only once")
    for name in names:
        if not name.strip() or "\n" in name or "\r" in name:
            raise ReplayInputError("a command must be one non-empty line")


def build_mock_data(commands: list[dict[str, str]]) -> str:
    """The Unicon mock-device YAML for ``commands`` (``[{"command", "output"}, ...]``)."""
    answers: dict[str, Any] = {name: {"response": [""]} for name in _CONNECT_COMMANDS}
    for item in commands:
        # ``\r`` would end a line early inside the mock; the parsers work on ``\n`` text.
        text = item["output"].replace("\r\n", "\n").replace("\r", "\n")
        answers[item["command"]] = {"response": [text]}
    data = {
        "connect": {
            "preface": "Trying mock_device ...\nConnected to mock_device.\n",
            "prompt": "R1>",
            "commands": {"": {"new_state": "execute"}},
        },
        "execute": {"prompt": PROMPT, "commands": answers},
    }
    return yaml.safe_dump(data, default_flow_style=False, allow_unicode=False)
