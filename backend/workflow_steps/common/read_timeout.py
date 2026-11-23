"""Shared ``read_timeout`` config parsing for Netmiko-touching steps."""

from __future__ import annotations

from typing import Any

from workflow_steps.common.step_flags import parse_int_flag

MIN_READ_TIMEOUT = 5
MAX_READ_TIMEOUT = 600


def parse_read_timeout(config: dict[str, Any], *, step_id: str, default: int) -> int:
    """Seconds to wait for a command's response before failing with a Netmiko
    "Pattern not detected" timeout."""
    return parse_int_flag(
        config,
        "read_timeout",
        default=default,
        minimum=MIN_READ_TIMEOUT,
        maximum=MAX_READ_TIMEOUT,
        step_id=step_id,
    )
