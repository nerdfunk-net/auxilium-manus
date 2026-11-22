"""Executor for the upload-binary step: copy a binary from a git repository to devices over SCP.

The file is read once from the repository checkout into a private temporary file while its MD5 is
computed (``source_file.snapshot_source_file``); the repository lease is released before the first
device is contacted, and every device receives that snapshot. When ``expected_md5`` is set the
snapshot must match it, otherwise nothing is sent. The device is asked for ``verify /md5`` before
the copy (an identical file is left alone) and after it, with the step's own ``read_timeout``;
a copy whose checksum is wrong, unreadable or timed out is deleted again. There is deliberately
no inline (TCL) transfer: it carries text only and would corrupt a binary.
"""

from __future__ import annotations

import asyncio
import logging
import posixpath
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.device_file_upload import (
    DeviceResult,
    RemoteTarget,
    build_upload_outcomes,
    delete_remote_file,
    fail_device,
    fail_device_from_exception,
    parse_socket_timeout,
    partition_device_results,
    record_transfer,
    remote_file_exists,
    run_on_devices,
    verify_remote_digest,
)
from workflow_steps.common.file_source_root import resolve_git_root
from workflow_steps.common.git_repository_loader import parse_repository_id
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.run_param_reference import resolve_config_reference
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.upload_binary.source_file import (
    SourceSnapshot,
    parse_expected_md5,
    snapshot_source_file,
)

logger = logging.getLogger(__name__)

_STEP_ID = "upload-binary"
# `verify /md5` of an IOS image on slow flash takes minutes: the longest wait the helper allows.
_DEFAULT_READ_TIMEOUT = 600
_VERIFY_ALGORITHM = "md5"
# Netmiko pastes the filesystem and file name into `dir` / `verify` / `delete` command lines, so
# anything that is not one token (a space, a line break) must not get there.
_DEVICE_TOKEN = re.compile(r"^\S+$")


@dataclass(frozen=True)
class _ParsedUploadBinary:
    credential_reference: str
    git_repository_id: int
    allow_stale_repository: bool
    source_path: str
    expected_md5: str | None
    destination_filename: str
    file_system: str
    overwrite: bool
    network_driver_override: str | None
    socket_timeout: int
    read_timeout: int


def _device_token(value: str, name: str) -> str:
    if not _DEVICE_TOKEN.match(value):
        raise ValueError(f"{_STEP_ID}: {name} must not contain spaces or line breaks")
    return value


def _parse_upload_binary(config: dict[str, Any]) -> _ParsedUploadBinary:
    repository_id = parse_repository_id(config.get("git_repository_id"), step_id=_STEP_ID)
    if repository_id is None:
        raise ValueError(f"{_STEP_ID}: git_repository_id is required")

    source_path = str(config.get("source_path") or "").strip().replace("\\", "/")
    if not source_path:
        raise ValueError(f"{_STEP_ID}: source_path is required")

    file_system = str(config.get("file_system") or "").strip()
    if not file_system:
        raise ValueError(f"{_STEP_ID}: file_system is required")

    destination_filename = str(config.get("destination_filename") or "").strip()
    if not destination_filename:
        destination_filename = posixpath.basename(source_path)
    if not destination_filename:
        raise ValueError(f"{_STEP_ID}: destination_filename is required")

    return _ParsedUploadBinary(
        credential_reference=str(config.get("credential_reference") or "").strip(),
        git_repository_id=repository_id,
        allow_stale_repository=parse_bool_flag(config, "allow_stale_repository"),
        source_path=source_path,
        expected_md5=parse_expected_md5(config.get("expected_md5"), step_id=_STEP_ID),
        destination_filename=_device_token(destination_filename, "destination_filename"),
        file_system=_device_token(file_system, "file_system"),
        overwrite=parse_bool_flag(config, "overwrite"),
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        socket_timeout=parse_socket_timeout(config, step_id=_STEP_ID),
        read_timeout=parse_read_timeout(config, step_id=_STEP_ID, default=_DEFAULT_READ_TIMEOUT),
    )


async def _take_snapshot(parsed: _ParsedUploadBinary) -> SourceSnapshot:
    """Copy the file out of the checkout, then release the repository lease.

    Both the "MD5 before" and the bytes sent come from this one read. The lease is held only for
    the copy: ``git_work_tree`` confirms it is still held right before it hands out the tree.
    """
    async with AsyncExitStack() as stack:
        root = await resolve_git_root(
            parsed.git_repository_id, stack, allow_stale=parsed.allow_stale_repository
        )
        snapshot = await asyncio.get_running_loop().run_in_executor(
            None, lambda: snapshot_source_file(root, parsed.source_path, step_id=_STEP_ID)
        )
    if parsed.expected_md5 is not None and snapshot.md5 != parsed.expected_md5:
        snapshot.discard()
        raise ValueError(
            f"{_STEP_ID}: md5 of {parsed.source_path} is {snapshot.md5}, expected "
            f"{parsed.expected_md5}; nothing was sent to any device"
        )
    return snapshot


def _with_rows(
    device: DeviceContext, node_id: str, rows: list[CommandResult]
) -> dict[str, list[CommandResult]]:
    results = dict(device.command_results)
    results[node_id] = rows
    return results


async def _upload_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    parsed: _ParsedUploadBinary,
    snapshot: SourceSnapshot,
    username: str,
    password: str,
    netmiko: NetmikoService,
) -> DeviceResult:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            step_id=_STEP_ID,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )
    try:
        return await _transfer_and_verify(
            device_id=device_id,
            device=device,
            node_id=node_id,
            host=host,
            parsed=parsed,
            snapshot=snapshot,
            username=username,
            password=password,
            netmiko=netmiko,
        )
    except Exception as exc:  # per device: connect/auth/scp errors must not abort the step
        return fail_device_from_exception(
            device=device, device_id=device_id, node_id=node_id, step_id=_STEP_ID, exc=exc
        )


async def _transfer_and_verify(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    host: str,
    parsed: _ParsedUploadBinary,
    snapshot: SourceSnapshot,
    username: str,
    password: str,
    netmiko: NetmikoService,
) -> DeviceResult:
    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=parsed.network_driver_override,
    )
    target = RemoteTarget(
        netmiko=netmiko,
        host=host,
        device=device,
        username=username,
        password=password,
        device_type=device_type,
        credential_reference=parsed.credential_reference,
    )
    named = {"file_system": parsed.file_system, "filename": parsed.destination_filename}
    on_device = f"{parsed.file_system}{parsed.destination_filename}"
    rows: list[CommandResult] = []

    def _fail(code: str, message: str, failure: Any = None) -> DeviceResult:
        return fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            step_id=_STEP_ID,
            code=code,
            message=message,
            failure=failure,
            command_results=_with_rows(device, node_id, rows),
        )

    exists, error, failure = await remote_file_exists(
        target, read_timeout=parsed.read_timeout, **named
    )
    if exists is None:
        return _fail("exists_check_failed", error or f"could not look for {on_device}", failure)

    if exists:
        before = await verify_remote_digest(
            target,
            node_id=node_id,
            algorithm=_VERIFY_ALGORITHM,
            local_digest=snapshot.md5,
            read_timeout=parsed.read_timeout,
            **named,
        )
        rows.append(before.command_result)
        if before.ok:
            rows.append(
                CommandResult(
                    node_id=node_id,
                    command=_STEP_ID,
                    success=True,
                    summary=(
                        f"{on_device} already present, md5 {snapshot.md5} verified on device; "
                        "not transferred"
                    ),
                )
            )
            return device_id, _ok(device, node_id, rows), True
        if before.device_digest is None:
            return _fail(
                "verify_failed",
                before.message or "md5 of the existing file is unreadable",
                before.failure,
            )
        if not parsed.overwrite:
            return _fail(
                "file_exists",
                f"{on_device} exists with a different md5 ({before.device_digest}) and "
                "overwrite is off",
            )

    result = await netmiko.upload_file(
        host=host,
        network_driver=device.network_driver,
        platform=device.platform,
        username=username,
        password=password,
        local_path=str(snapshot.path),
        dest_file=parsed.destination_filename,
        file_system=parsed.file_system,
        overwrite=exists,
        inline_transfer=False,  # text only: never for a binary
        socket_timeout=parsed.socket_timeout,
        device_type=device_type,
        credential_reference=parsed.credential_reference,
        verify_file=False,  # verified below, with this step's own read_timeout
    )
    results, failed_transfer = record_transfer(
        device=device,
        device_id=device_id,
        node_id=node_id,
        step_id=_STEP_ID,
        command=_STEP_ID,
        result=result,
        ok_summary=f"copied {snapshot.size_bytes} bytes to {on_device}",
        default_error="Binary upload failed",
    )
    rows.extend(results[node_id])
    if failed_transfer is not None:
        return _fail("upload_failed", result.error or "Binary upload failed", result.failure)

    after = await verify_remote_digest(
        target,
        node_id=node_id,
        algorithm=_VERIFY_ALGORITHM,
        local_digest=snapshot.md5,
        read_timeout=parsed.read_timeout,
        **named,
    )
    rows.append(after.command_result)
    if not after.ok:
        # The copy is on the device but not proven good: remove it rather than leave an image
        # that looks bootable behind a failed step.
        removed = await delete_remote_file(target, read_timeout=parsed.read_timeout, **named)
        suffix = (
            "the file was removed from the device"
            if removed
            else ("the file could NOT be removed from the device")
        )
        return _fail(
            "verify_failed",
            f"{after.message or 'md5 not verified'}; {suffix}",
            after.failure,
        )
    return device_id, _ok(device, node_id, rows), True


def _ok(device: DeviceContext, node_id: str, rows: list[CommandResult]) -> DeviceContext:
    return device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "command_results": _with_rows(device, node_id, rows),
        }
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service  # the bytes come from the repository, not from an artifact
    parsed = replace(
        _parse_upload_binary(config),
        credential_reference=resolve_config_reference(
            config,
            source_key="credential_source",
            param_key="credential_param",
            literal_key="credential_reference",
            run_inputs=run.run_inputs,
        ),
    )

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)

    run_id = run.id
    logger.info(
        "upload-binary started run_id=%s node_id=%s devices=%d repository=%s source=%s "
        "destination=%s%s",
        run_id,
        node_id,
        len(context.devices),
        parsed.git_repository_id,
        parsed.source_path,
        parsed.file_system,
        parsed.destination_filename,
    )

    results: list[DeviceResult] = []
    if context.devices:
        snapshot = await _take_snapshot(parsed)
        try:
            logger.info(
                "upload-binary source ready run_id=%s bytes=%d md5=%s",
                run_id,
                snapshot.size_bytes,
                snapshot.md5,
            )

            async def _work(device_id: str, device: DeviceContext) -> DeviceResult:
                return await _upload_on_device(
                    device_id=device_id,
                    device=device,
                    node_id=node_id,
                    parsed=parsed,
                    snapshot=snapshot,
                    username=username,
                    password=password,
                    netmiko=netmiko,
                )

            results = await run_on_devices(
                step_label=_STEP_ID, context=context, run_id=run_id, work=_work
            )
        finally:
            snapshot.discard()

    success_devices, failed_devices = partition_device_results(results)
    logger.info(
        "upload-binary finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run_id,
    )
    return build_upload_outcomes(
        context=context,
        success_devices=success_devices,
        failed_devices=failed_devices,
        noun="binary",
    )
