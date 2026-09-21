"""Shared connect-phase retry config parsing for Netmiko-touching steps.

See ``services.network.netmiko.connection.RetryPolicy`` for what this
produces and where it's consumed.
"""

from __future__ import annotations

import json
from typing import Any

from services.network.netmiko.connection import RetryPolicy

MAX_RETRY_ATTEMPTS = 5
MIN_RETRY_BACKOFF_SECONDS = 1
MAX_RETRY_BACKOFF_SECONDS = 600


def parse_retry_backoff_seconds(config: dict[str, Any], *, step_id: str) -> RetryPolicy:
    """Parse ``retry_backoff_seconds`` (a list of per-retry delays, in order) into
    a ``RetryPolicy``. Empty/absent means no retry — identical to prior behavior
    for every step that adopts this. Accepts the same JSON-or-newline-separated
    string fallback other list fields (e.g. run-command's ``commands``) use, for
    UI paste convenience.
    """
    raw = config.get("retry_backoff_seconds")
    if raw is None:
        raw = []
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            raw = []
        else:
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError:
                raw = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not isinstance(raw, list):
        raise ValueError(f"{step_id}: retry_backoff_seconds must be a list of integers")

    try:
        delays = [int(value) for value in raw]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{step_id}: retry_backoff_seconds must be a list of integers") from exc

    if len(delays) > MAX_RETRY_ATTEMPTS:
        raise ValueError(
            f"{step_id}: retry_backoff_seconds cannot have more than {MAX_RETRY_ATTEMPTS} entries"
        )
    for delay in delays:
        if not (MIN_RETRY_BACKOFF_SECONDS <= delay <= MAX_RETRY_BACKOFF_SECONDS):
            raise ValueError(
                f"{step_id}: each retry_backoff_seconds value must be between "
                f"{MIN_RETRY_BACKOFF_SECONDS} and {MAX_RETRY_BACKOFF_SECONDS} seconds"
            )
    return RetryPolicy(backoff_seconds=tuple(delays))
