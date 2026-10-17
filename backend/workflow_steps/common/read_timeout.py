"""Shared ``read_timeout`` config parsing for Netmiko-touching steps."""

from __future__ import annotations

from typing import Any

MIN_READ_TIMEOUT = 5
MAX_READ_TIMEOUT = 600


def parse_read_timeout(config: dict[str, Any], *, step_id: str, default: int) -> int:
    """Seconds to wait for a command's response before failing with a Netmiko
    "Pattern not detected" timeout."""
    raw = config.get("read_timeout")
    if raw in (None, ""):
        raw = default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{step_id}: read_timeout must be an integer") from exc
    if not (MIN_READ_TIMEOUT <= value <= MAX_READ_TIMEOUT):
        raise ValueError(
            f"{step_id}: read_timeout must be between {MIN_READ_TIMEOUT} "
            f"and {MAX_READ_TIMEOUT} seconds"
        )
    return value
