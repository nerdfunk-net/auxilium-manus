"""merge_running_config: which device-side CLI errors count as a failed merge (W3a-06).

The merge path scans the transcript for ``%error`` / ``invalid input`` / ``%warning``. The
Netmiko config path (deploy) has a longer marker list that also knows an authorization refusal;
a TACACS+ command-authorization failure during ``copy ... running-config`` is read as success
today.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.network.netmiko.connection import NetmikoDeviceSession
from tests.unit._step_helpers import strict_xfail


def _merge(transcript: str):  # noqa: ANN202
    session = NetmikoDeviceSession(
        host="10.0.0.1", device_type="cisco_ios", username="a", password="b"
    )
    with patch("services.network.netmiko.connection.ConnectHandler") as cls:
        connection = cls.return_value
        connection.base_prompt = "R1"
        connection.RETURN = "\n"
        connection.send_command.return_value = transcript
        return session.merge_running_config("flash:x.cfg")


def test_a_clean_transcript_is_a_success() -> None:
    assert _merge("[OK]\n12 bytes copied in 0.1 secs\nR1#").success


@pytest.mark.parametrize(
    "line",
    [
        "%Error opening flash:x.cfg (No such file)",
        "% Invalid input detected at '^' marker.",
        "%Warning: x",
    ],
)
def test_the_known_error_lines_fail_the_merge(line: str) -> None:
    result = _merge(f"{line}\nR1#")

    assert not result.success
    assert result.failure is not None
    assert result.failure.kind == "config_rejected"


@strict_xfail("W3a-06", "'Command authorization failed.' is not in the merge marker list")
def test_an_authorization_refusal_fails_the_merge() -> None:
    result = _merge("Command authorization failed.\nR1#")

    assert not result.success
