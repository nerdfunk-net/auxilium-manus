"""Shim jobs of configure-replace-config: one job per device and the diff command.

Every job gets the step's job budget as an argument and answers a ``ShimResult``; a client-side
timeout is the ``outcome_unknown`` flag (W3a-07), never a sentence searched for in the message.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from models.failure import FailureInfo
from services.pyats.batch import cap_shim_text, shim_device_failure
from services.pyats.common.exceptions import PyATSAPIError
from services.pyats.credentials import PyATSCredentials

logger = logging.getLogger(__name__)


STEP_ID = "configure-replace-config"


@dataclass(frozen=True)
class ShimResult:
    """One shim job for one device.

    ``ok`` is False only when the connection or the job itself failed; each entry of
    ``entries`` (keyed by command text) can still carry its own per-command ``error``.
    ``outcome_unknown`` says the client gave up waiting (C4-01): the device may have run it.
    """

    ok: bool
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str | None = None
    failure: FailureInfo | None = None
    outcome_unknown: bool = False


async def run_shim_job(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    operation: str,
    shim_device: dict[str, Any],
    commands: list[str],
    timeout: float,
) -> ShimResult:
    """Run a shim job with one or more commands over a single device connection.

    The shim connects once, runs every command in ``commands`` against that same connection in
    order, then disconnects -- see generic_script.py's ``run_commands``. ``timeout`` is the job
    budget in seconds (``job_timeout_seconds`` of the step).
    """
    try:
        response = await shim.run_job(
            shim_credentials,
            operation=operation,
            devices=[shim_device],
            commands=commands,
            timeout_seconds=timeout,
        )
    except PyATSAPIError as exc:
        message = str(exc)
        return ShimResult(
            ok=False,
            error=message,
            failure=exc.failure,
            # A client-side timeout says nothing about what the device did (C4-01).
            outcome_unknown=exc.code == "timeout" or "timed out" in message,
        )

    result = (response.get("results") or {}).get(shim_device["name"])
    if not result or not result.get("success", False):
        message, failure = shim_device_failure(result)
        return ShimResult(ok=False, error=message, failure=failure)

    return ShimResult(ok=True, entries=result.get("commands") or {})


async def call_shim(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    operation: str,
    shim_device: dict[str, Any],
    command: str,
    timeout: float,
) -> tuple[bool, Any, str | None]:
    """Run a single-command shim job. Returns (ok, value, error_message)."""
    result = await run_shim_job(
        shim,
        shim_credentials,
        operation=operation,
        shim_device=shim_device,
        commands=[command],
        timeout=timeout,
    )
    if not result.ok:
        return False, None, result.error

    entry = result.entries.get(command) or {}
    if entry.get("error"):
        # A per-command error is the device's exception chain: stored capped (R4-01).
        return False, None, cap_shim_text(str(entry["error"]))

    value = entry.get("parsed") if operation == "learn" else entry.get("raw")
    return True, value, None


async def run_diff(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    shim_device: dict[str, Any],
    diff_command: str,
    timeout: float,
) -> tuple[bool, str, str | None]:
    """Run the config-text diff command. Returns (ok, diff_text, error_message)."""
    ok, raw, err = await call_shim(
        shim,
        shim_credentials,
        operation="execute",
        shim_device=shim_device,
        command=diff_command,
        timeout=timeout,
    )
    if not ok:
        return False, "", err
    return True, str(raw or ""), None
