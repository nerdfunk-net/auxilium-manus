"""Shared mechanics of the steps that copy a file to a device over SCP.

``upload-config`` (text produced by an earlier step) and ``upload-binary`` (a file from a git
repository) differ in where the bytes come from; everything after that is the same: per-device
concurrency with start/finish log lines, the transfer record on the device, the ``success`` /
``failure`` split and the socket-timeout setting. It lives here so neither step copies the other.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from models.failure import FailureInfo
from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.network.netmiko.connection import FileTransferResult
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.partial_outcomes import device_error_from_exception

logger = logging.getLogger(__name__)

MIN_SOCKET_TIMEOUT = 5
MAX_SOCKET_TIMEOUT = 300
DEFAULT_SOCKET_TIMEOUT = 10

# Matches Cisco IOS/IOS-XE `verify /<algo> (<fs><file>) = <hex>` output; ignores any
# other banner/progress lines (e.g. the leading ".Done!").
VERIFY_HASH_PATTERN = re.compile(r"verify\s+/\S+\s+\([^)]*\)\s*=\s*([0-9a-fA-F]+)", re.IGNORECASE)
# What `dir <file>` prints when the file is not there (the same markers Netmiko looks for).
_MISSING_FILE_MARKERS = ("Error opening", "No such file or directory", "Path does not exist")

# (device id, updated device, ok)
DeviceResult = tuple[str, DeviceContext, bool]


def parse_socket_timeout(config: dict[str, Any], *, step_id: str) -> int:
    """SCP/SFTP socket timeout in seconds (per socket operation, not for the whole transfer)."""
    raw = config.get("socket_timeout")
    if raw in (None, ""):
        raw = DEFAULT_SOCKET_TIMEOUT
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{step_id}: socket_timeout must be an integer") from exc
    if not (MIN_SOCKET_TIMEOUT <= value <= MAX_SOCKET_TIMEOUT):
        raise ValueError(
            f"{step_id}: socket_timeout must be between {MIN_SOCKET_TIMEOUT} "
            f"and {MAX_SOCKET_TIMEOUT} seconds"
        )
    return value


def fail_device(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    step_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
    command_results: dict[str, list[CommandResult]] | None = None,
) -> DeviceResult:
    """Mark one device ``FAILED`` with a ``DeviceError`` (the step goes on with the others)."""
    err = DeviceError(node_id=node_id, step_id=step_id, code=code, message=message, failure=failure)
    update: dict[str, Any] = {
        "status": DeviceStatus.FAILED,
        "errors": [*device.errors, err],
    }
    if command_results is not None:
        update["command_results"] = command_results
    return device_id, device.model_copy(update=update), False


def record_transfer(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    step_id: str,
    command: str,
    result: FileTransferResult,
    ok_summary: str,
    default_error: str,
) -> tuple[dict[str, list[CommandResult]], DeviceResult | None]:
    """Record the transfer on the device. Returns the new ``command_results`` and, when the
    transfer failed, the failed-device result the caller returns as it is."""
    summary = ok_summary if result.success else (result.error or default_error)
    command_results = dict(device.command_results)
    command_results[node_id] = [
        CommandResult(node_id=node_id, command=command, success=result.success, summary=summary)
    ]
    if result.success:
        return command_results, None
    return command_results, fail_device(
        device=device,
        device_id=device_id,
        node_id=node_id,
        step_id=step_id,
        code="upload_failed",
        message=result.error or default_error,
        failure=result.failure,
        command_results=command_results,
    )


async def run_on_devices(
    *,
    step_label: str,
    context: WorkflowContext,
    run_id: Any,
    work: Callable[[str, DeviceContext], Awaitable[DeviceResult]],
) -> list[DeviceResult]:
    """Run ``work`` for every device concurrently, with a start and a finish line per device."""
    total = len(context.devices)

    async def _one(index: int, device_id: str, device: DeviceContext) -> DeviceResult:
        host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
        logger.info(
            "%s device %d/%d id=%s host=%s: connecting run_id=%s",
            step_label,
            index,
            total,
            device_id,
            host,
            run_id,
        )
        result = await work(device_id, device)
        logger.info(
            "%s device %d/%d id=%s host=%s: %s run_id=%s",
            step_label,
            index,
            total,
            device_id,
            host,
            "ok" if result[2] else "failed",
            run_id,
        )
        return result

    return list(
        await asyncio.gather(
            *[
                _one(index, device_id, device)
                for index, (device_id, device) in enumerate(context.devices.items(), start=1)
            ]
        )
    )


def partition_device_results(
    results: list[DeviceResult],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device
    return success_devices, failed_devices


def build_upload_outcomes(
    *,
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
    noun: str,
) -> list[StepOutcome]:
    """``success`` always, ``failure`` only when a device failed. ``noun``: "config", "binary"."""
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"uploaded {noun} to {len(success_devices)} device(s)",
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
                summary=f"{len(failed_devices)} device(s) failed",
            )
        )
    return outcomes


def fail_device_from_exception(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    step_id: str,
    exc: BaseException,
) -> DeviceResult:
    """Fail one device from an exception raised while connecting or copying.

    The message is the step's own text for a ``ValueError`` and only the class name for anything
    else, so driver text never reaches the stored run; the structured ``FailureInfo`` keeps the
    reason (``device_error_from_exception``).
    """
    err = device_error_from_exception(exc, node_id=node_id, step_id=step_id)
    failed = device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )
    return device_id, failed, False


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

    def _failed(message: str, failure: FailureInfo | None, digest: str | None):
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
        return _failed(result.error or f"verify command failed: {command}", result.failure, None)

    output = result.command_outputs.get(command, "") or result.output
    match = VERIFY_HASH_PATTERN.search(output)
    if match is None:
        return _failed(
            f"Could not parse a {algorithm} checksum from the device's verify output", None, None
        )

    device_digest = match.group(1).lower()
    if device_digest != local_digest.lower():
        return _failed(
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
