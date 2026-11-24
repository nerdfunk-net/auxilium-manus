"""merge_running_config: which device-side CLI errors count as a failed merge (W3a-02, W3a-06).

The merge path uses the shared marker list of ``output_check`` (plus the copy-specific
``%Error opening`` and ``%Warning`` lines), reports a closed label and never copies the
device line into the error text. ``fail_on_cli_error=False`` ignores refusals and warnings
but not an unreadable source file.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from services.network.netmiko.connection import NetmikoDeviceSession


def _merge(transcript: str, **kwargs: bool):  # noqa: ANN202
    session = NetmikoDeviceSession(
        host="10.0.0.1", device_type="cisco_ios", username="a", password="b"
    )
    with patch("services.network.netmiko.connection.ConnectHandler") as cls:
        connection = cls.return_value
        connection.base_prompt = "R1"
        connection.RETURN = "\n"
        connection.send_command.return_value = transcript
        return session.merge_running_config("flash:x.cfg", **kwargs)


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


def test_an_authorization_refusal_fails_the_merge() -> None:
    result = _merge("Command authorization failed.\nR1#")

    assert not result.success
    assert result.failure is not None
    assert result.failure.kind == "config_rejected"
    assert result.error is not None
    assert "authorization_failed" in result.error


@pytest.mark.parametrize(
    ("line", "label"),
    [
        ("%Error opening flash:x.cfg (No such file)", "copy_error_opening"),
        ("%Warning: x", "copy_warning"),
        ("% Invalid input detected at '^' marker.", "invalid_input"),
    ],
)
def test_the_error_names_a_label_and_the_line_never_the_device_text(
    line: str, label: str
) -> None:
    result = _merge(f"[OK]\n{line}\nR1#")

    assert result.error is not None
    assert label in result.error
    assert "line 2" in result.error
    assert "flash:x.cfg (No such" not in result.error
    assert "marker" not in result.error


def test_a_secret_echoed_in_a_refused_line_is_not_copied() -> None:
    result = _merge("% Invalid input detected at '^' marker: tacacs-server key hunter2\nR1#")

    assert result.error is not None
    assert "hunter2" not in result.error


@pytest.mark.parametrize(
    "line",
    [
        "Command authorization failed.",
        "%Warning: x",
        "% Invalid input detected at '^' marker.",
    ],
)
def test_fail_on_cli_error_off_ignores_refusals_and_warnings(line: str) -> None:
    assert _merge(f"{line}\nR1#", fail_on_cli_error=False).success


def test_fail_on_cli_error_off_still_fails_an_unreadable_source_file() -> None:
    result = _merge("%Error opening flash:x.cfg (No such file)\nR1#", fail_on_cli_error=False)

    assert not result.success
    assert result.error is not None
    assert "copy_error_opening" in result.error
