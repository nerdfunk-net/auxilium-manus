"""Shim jobs of configure-replace-config: one job per device, the diff command, the error type."""

from __future__ import annotations

import contextvars
import logging
from typing import TYPE_CHECKING, Any

from models.failure import FailureInfo
from services.pyats.common.exceptions import PyATSAPIError
from services.pyats.credentials import PyATSCredentials
from workflow_steps.common.pyats_batch import (
    shim_device_failure,
)

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


STEP_ID = "configure-replace-config"


class ShimError(str):
    """An error message that also carries the closed-vocabulary classification of its cause."""

    failure: FailureInfo | None

    def __new__(cls, message: str, failure: FailureInfo | None = None) -> ShimError:
        instance = super().__new__(cls, message)
        instance.failure = failure
        return instance


# Job budget of this step run (seconds); set by execute() before the per-device tasks start.
JOB_TIMEOUT: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "configure_replace_job_timeout", default=None
)

OUTCOME_UNKNOWN = (
    " -- the job may still have been applied on the device; check it before re-running"
)


async def run_shim_job(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    operation: str,
    shim_device: dict[str, Any],
    commands: list[str],
) -> tuple[bool, dict[str, dict[str, Any]], str | None]:
    """Run a shim job with one or more commands over a single device connection.

    The shim connects once, runs every command in ``commands`` against that
    same connection in order, then disconnects -- see generic_script.py's
    ``run_commands``. Returns (ok, command_entries, error_message); ``ok`` is
    False only when the connection/job itself failed for this device (each
    entry in ``command_entries`` -- keyed by command text -- can still carry
    its own per-command ``error`` even when ``ok`` is True).
    """
    try:
        response = await shim.run_job(
            shim_credentials,
            operation=operation,
            devices=[shim_device],
            commands=commands,
            timeout_seconds=JOB_TIMEOUT.get(),
        )
    except PyATSAPIError as exc:
        message = str(exc)
        if exc.code == "timeout" or "timed out" in message:
            # A client-side timeout says nothing about what the device did (C4-01).
            message += OUTCOME_UNKNOWN
        return False, {}, ShimError(message, exc.failure)

    result = (response.get("results") or {}).get(shim_device["name"])
    if not result or not result.get("success", False):
        message, failure = shim_device_failure(result)
        return False, {}, ShimError(message, failure)

    return True, result.get("commands") or {}, None


async def call_shim(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    operation: str,
    shim_device: dict[str, Any],
    command: str,
) -> tuple[bool, Any, str | None]:
    """Run a single-command shim job. Returns (ok, value, error_message)."""
    ok, command_entries, err = await run_shim_job(
        shim, shim_credentials, operation=operation, shim_device=shim_device, commands=[command]
    )
    if not ok:
        return False, None, err

    entry = command_entries.get(command) or {}
    if entry.get("error"):
        return False, None, entry["error"]

    value = entry.get("parsed") if operation == "learn" else entry.get("raw")
    return True, value, None


async def run_diff(
    shim: Any,
    shim_credentials: PyATSCredentials,
    *,
    shim_device: dict[str, Any],
    diff_command: str,
) -> tuple[bool, str, str | None]:
    """Run the config-text diff command. Returns (ok, diff_text, error_message)."""
    ok, raw, err = await call_shim(
        shim,
        shim_credentials,
        operation="execute",
        shim_device=shim_device,
        command=diff_command,
    )
    if not ok:
        return False, "", err
    return True, str(raw or ""), None
