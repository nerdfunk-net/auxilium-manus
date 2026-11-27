"""Shared mechanics of the steps that copy a file to a device over SCP.

``upload-config`` (text produced by an earlier step) and ``upload-binary`` (a file from a git
repository) differ in where the bytes come from; everything after that is the same: per-device
concurrency with start/finish log lines, the transfer record on the device, the ``success`` /
``failure`` split and the socket-timeout setting. It lives here so neither step copies the other.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from models.failure import FailureInfo
from models.workflow_context import (
    CommandResult,
    DeviceContext,
    StepOutcome,
    WorkflowContext,
)
from services.network.netmiko.connection import FileTransferResult
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Batch, Fail
from workflow_steps.common.step_flags import parse_int_flag

logger = logging.getLogger(__name__)

MIN_SOCKET_TIMEOUT = 5
MAX_SOCKET_TIMEOUT = 300
DEFAULT_SOCKET_TIMEOUT = 10

# Matches Cisco IOS/IOS-XE `verify /<algo> (<fs><file>) = <hex>` output; ignores any
# other banner/progress lines (e.g. the leading ".Done!").
VERIFY_HASH_PATTERN = re.compile(r"verify\s+/\S+\s+\([^)]*\)\s*=\s*([0-9a-fA-F]+)", re.IGNORECASE)
# What `dir <file>` prints when the file is not there (the same markers Netmiko looks for).
_MISSING_FILE_MARKERS = ("Error opening", "No such file or directory", "Path does not exist")

# A file-system or file name is pasted into a CLI line (``copy``, ``verify``, ``configure
# replace``); anything that is not one token (a space, a line break) must not get there.
_DEVICE_TOKEN = re.compile(r"^\S+$")


def parse_device_token(value: str, *, name: str, step_id: str) -> str:
    """``value`` when it is one token, else a ``ValueError`` naming the step and the field."""
    if not _DEVICE_TOKEN.match(value):
        raise ValueError(f"{step_id}: {name} must not contain spaces or line breaks")
    return value


def parse_socket_timeout(config: dict[str, Any], *, step_id: str) -> int:
    """SCP/SFTP socket timeout in seconds (per socket operation, not for the whole transfer)."""
    return parse_int_flag(
        config,
        "socket_timeout",
        default=DEFAULT_SOCKET_TIMEOUT,
        minimum=MIN_SOCKET_TIMEOUT,
        maximum=MAX_SOCKET_TIMEOUT,
        step_id=step_id,
    )


def transfer_command_results(
    *,
    device: DeviceContext,
    node_id: str,
    command: str,
    result: FileTransferResult,
    ok_summary: str,
    default_error: str,
) -> dict[str, list[CommandResult]]:
    """The device's ``command_results`` with the transfer recorded under ``node_id``."""
    summary = ok_summary if result.success else (result.error or default_error)
    command_results = dict(device.command_results)
    command_results[node_id] = [
        CommandResult(node_id=node_id, command=command, success=result.success, summary=summary)
    ]
    return command_results


def record_transfer(
    *,
    device: DeviceContext,
    node_id: str,
    command: str,
    result: FileTransferResult,
    ok_summary: str,
    default_error: str,
) -> tuple[dict[str, list[CommandResult]], Fail | None]:
    """Record the transfer on the device. Returns the new ``command_results`` and, when the
    transfer failed, the ``Fail`` the caller returns as it is (it carries the device with the
    record, so the failed device keeps it). A step that builds its own failure
    (``upload-binary``, which also keeps its verification rows) uses
    ``transfer_command_results`` instead."""
    command_results = transfer_command_results(
        device=device,
        node_id=node_id,
        command=command,
        result=result,
        ok_summary=ok_summary,
        default_error=default_error,
    )
    if result.success:
        return command_results, None
    return command_results, Fail(
        "upload_failed",
        result.error or default_error,
        result.failure,
        device=device.model_copy(update={"command_results": command_results}),
    )


def upload_outcomes(context: WorkflowContext, batch: Batch, *, noun: str) -> list[StepOutcome]:
    """``success`` always, ``failure`` only when a device failed. ``noun``: "config", "binary"."""
    return build_outcomes(
        context,
        batch.ok,
        batch.failed,
        success_summary=f"uploaded {noun} to {len(batch.ok)} device(s)",
        failure_summary=f"{len(batch.failed)} device(s) failed",
    )


@dataclass(frozen=True)
class RemoteTarget:
    """One device a step talks to over the pooled Netmiko session."""

    netmiko: NetmikoService
    host: str
    device: DeviceContext
    username: str
    password: str
    device_type: str | None
    credential_reference: str

    async def run(self, command: str, *, read_timeout: int | None = None) -> Any:
        return await self.netmiko.send_commands(
            host=self.host,
            network_driver=self.device.network_driver,
            platform=self.device.platform,
            username=self.username,
            password=self.password,
            commands=[command],
            device_type=self.device_type,
            credential_reference=self.credential_reference,
            read_timeout=read_timeout,
        )


@dataclass(frozen=True)
class RemoteDigestCheck:
    """Result of comparing the device's checksum of a file with the local one.

    ``device_digest`` is ``None`` when the device's answer could not be read (the command failed
    or its output had no checksum), which is not the same as a mismatch.
    """

    ok: bool
    command_result: CommandResult
    message: str | None
    failure: FailureInfo | None
    device_digest: str | None


async def verify_remote_digest(
    target: RemoteTarget,
    *,
    node_id: str,
    file_system: str,
    filename: str,
    algorithm: str,
    local_digest: str,
    read_timeout: int | None = None,
) -> RemoteDigestCheck:
    """Run ``verify /<algorithm> <fs><file>`` on the device and compare it with ``local_digest``."""
    command = f"verify /{algorithm} {file_system}{filename}"

    def _unverified(message: str, failure: FailureInfo | None, digest: str | None):
        return RemoteDigestCheck(
            ok=False,
            command_result=CommandResult(
                node_id=node_id, command=command, success=False, summary=message
            ),
            message=message,
            failure=failure,
            device_digest=digest,
        )

    result = await target.run(command, read_timeout=read_timeout)
    if not result.success:
        return _unverified(
            result.error or f"verify command failed: {command}", result.failure, None
        )

    output = result.command_outputs.get(command, "") or result.output
    match = VERIFY_HASH_PATTERN.search(output)
    if match is None:
        return _unverified(
            f"Could not parse a {algorithm} checksum from the device's verify output", None, None
        )

    device_digest = match.group(1).lower()
    if device_digest != local_digest.lower():
        return _unverified(
            f"{algorithm} mismatch: expected {local_digest}, device reported {device_digest}",
            None,
            device_digest,
        )
    return RemoteDigestCheck(
        ok=True,
        command_result=CommandResult(
            node_id=node_id,
            command=command,
            success=True,
            summary=f"{algorithm} checksum verified ({device_digest})",
        ),
        message=None,
        failure=None,
        device_digest=device_digest,
    )


async def remote_file_exists(
    target: RemoteTarget,
    *,
    file_system: str,
    filename: str,
    read_timeout: int | None = None,
) -> tuple[bool | None, str | None, FailureInfo | None]:
    """``(exists, error, failure)``: ``exists`` is ``None`` when the device's answer is unclear."""
    command = f"dir {file_system}{filename}"
    result = await target.run(command, read_timeout=read_timeout)
    if not result.success:
        return None, result.error or f"command failed: {command}", result.failure
    output = result.command_outputs.get(command, "") or result.output
    if any(marker in output for marker in _MISSING_FILE_MARKERS):
        return False, None, None
    if "Directory of" in output:
        return True, None, None
    return None, f"Unexpected output from {command}", None


async def delete_remote_file(
    target: RemoteTarget, *, file_system: str, filename: str, read_timeout: int | None = None
) -> bool:
    """Best-effort ``delete /force``; ``True`` when the device accepted it. Never raises."""
    try:
        result = await target.run(
            f"delete /force {file_system}{filename}", read_timeout=read_timeout
        )
    except Exception:  # best effort: the caller already reports the original failure
        logger.warning("could not delete the remote file after a failed upload", exc_info=True)
        return False
    return bool(result.success)
