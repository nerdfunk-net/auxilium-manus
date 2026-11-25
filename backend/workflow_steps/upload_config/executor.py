"""Executor for the upload-config step."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass, replace
from typing import Any

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool
from workflow_steps.common.content_resolver import (
    AMBIGUOUS_CONTENT_CODE,
    AMBIGUOUS_CONTENT_FAILURE,
    CONTENT_SOURCES,
    list_exportable_content,
    single_item_or_message,
)
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.device_file_upload import (
    RemoteTarget,
    parse_device_token,
    parse_socket_timeout,
    record_transfer,
    upload_outcomes,
    verify_remote_digest,
)
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.device_type import connection_device_type
from workflow_steps.common.failure_records import INVALID_INPUT, MISSING_DATA
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_param_reference import resolve_config_reference
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_bool_flag

logger = logging.getLogger(__name__)

_STEP_ID = "upload-config"
_SOURCE_STEP_ID_EXEMPT = frozenset({"running_config", "startup_config", "latest_command_output"})
_VERIFY_ALGORITHMS = frozenset({"md5", "sha512"})
# Cisco IOS/IOS-XE unconditionally append one extra "\n" to whatever bytes were
# actually sent when storing a text file — confirmed in Netmiko's own cisco_ios.py
# file_md5()/config_md5() ("Cisco IOS automatically adds this": `file_contents + "\n"`,
# with no stripping of any newline already present first) and empirically: uploading
# content that already ended in a single "\n" produced a device checksum matching that
# content plus a *second* trailing "\n" (a trailing blank line), not a normalized
# single newline. Both device types resolve to the same CiscoIosSSH/
# CiscoIosFileTransfer driver in Netmiko. Other platforms (NX-OS, ASA, Junos, EOS, …)
# have no such documented behavior, so the adjustment below is scoped to these two.
_NEWLINE_APPENDED_DEVICE_TYPES = frozenset({"cisco_ios", "cisco_xe"})


@dataclass(frozen=True)
class _ParsedUploadConfig:
    credential_reference: str
    content_source: str
    source_step_node_id: str | None
    parsed_output_key: str | None
    destination_filename: str
    file_system: str
    overwrite: bool
    inline_transfer: bool
    network_driver_override: str | None
    socket_timeout: int
    verify_content: bool
    verify_algorithm: str


def _parse_verify_algorithm(config: dict[str, Any]) -> str:
    value = str(config.get("verify_algorithm") or "md5").strip().lower()
    if value not in _VERIFY_ALGORITHMS:
        raise ValueError(
            f"upload-config: verify_algorithm must be one of {sorted(_VERIFY_ALGORITHMS)}"
        )
    return value


def _parse_upload_config(config: dict[str, Any]) -> _ParsedUploadConfig:
    content_source = str(config.get("content_source") or "updated_content").strip().lower()
    if content_source not in CONTENT_SOURCES:
        raise ValueError(
            f"upload-config: content_source {content_source!r} must be one of "
            f"{sorted(CONTENT_SOURCES)}"
        )

    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    if content_source not in _SOURCE_STEP_ID_EXEMPT and not source_step_node_id:
        raise ValueError(
            f"upload-config: source_step_node_id is required for content_source {content_source!r}"
        )

    destination_filename = str(config.get("destination_filename") or "").strip()
    if not destination_filename:
        raise ValueError("upload-config: destination_filename is required")

    file_system = str(config.get("file_system") or "").strip()
    if not file_system:
        raise ValueError("upload-config: file_system is required")

    return _ParsedUploadConfig(
        credential_reference=str(config.get("credential_reference") or "").strip(),
        content_source=content_source,
        source_step_node_id=source_step_node_id,
        parsed_output_key=str(config.get("parsed_output_key") or "").strip() or None,
        destination_filename=parse_device_token(
            destination_filename, name="destination_filename", step_id="upload-config"
        ),
        file_system=parse_device_token(file_system, name="file_system", step_id="upload-config"),
        overwrite=parse_bool_flag(config, "overwrite"),
        inline_transfer=parse_bool_flag(config, "inline_transfer"),
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        socket_timeout=parse_socket_timeout(config, step_id=_STEP_ID),
        verify_content=parse_bool_flag(config, "verify_content"),
        verify_algorithm=_parse_verify_algorithm(config),
    )


async def _load_upload_content(
    *,
    device: DeviceContext,
    parsed: _ParsedUploadConfig,
    artifact_service: ArtifactService,
) -> str | Fail:
    items = list_exportable_content(
        device,
        content_source=parsed.content_source,
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
        step_id=_STEP_ID,
    )
    if not items:
        return Fail(
            f"{parsed.content_source}_missing",
            f"No {parsed.content_source} found for the configured source",
            failure=MISSING_DATA,
        )
    if (ambiguous := single_item_or_message(items)) is not None:
        # A multi-command source would otherwise upload the first command's output (W3a-03).
        return Fail(AMBIGUOUS_CONTENT_CODE, ambiguous, failure=AMBIGUOUS_CONTENT_FAILURE)
    return await artifact_service.resolve(items[0].artifact_ref)


def _compute_local_digest(content: str, algorithm: str, *, device_type: str | None) -> str:
    if device_type in _NEWLINE_APPENDED_DEVICE_TYPES:
        content = content + "\n"
    data = content.encode("utf-8")
    if algorithm == "md5":
        # Matches Cisco's `verify /md5` output; used for integrity comparison against
        # vendor CLI tooling, not as a security control.
        digest = hashlib.md5(data)  # noqa: S324
    else:
        digest = hashlib.sha512(data)
    return digest.hexdigest()


async def _verify_uploaded_content(
    *,
    host: str,
    device: DeviceContext,
    node_id: str,
    parsed: _ParsedUploadConfig,
    content_text: str,
    username: str,
    password: str,
    netmiko: NetmikoService,
    device_type: str | None,
) -> tuple[bool, CommandResult, str | None, FailureInfo | None]:
    check = await verify_remote_digest(
        RemoteTarget(
            netmiko=netmiko,
            host=host,
            device=device,
            username=username,
            password=password,
            device_type=device_type,
            credential_reference=parsed.credential_reference,
        ),
        node_id=node_id,
        file_system=parsed.file_system,
        filename=parsed.destination_filename,
        algorithm=parsed.verify_algorithm,
        local_digest=_compute_local_digest(
            content_text, parsed.verify_algorithm, device_type=device_type
        ),
    )
    return check.ok, check.command_result, check.message, check.failure


async def _upload_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    parsed: _ParsedUploadConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> DeviceContext | Fail:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return Fail(
            "missing_host",
            f"Device {device_id} has no hostname or primary IP",
            failure=INVALID_INPUT,
        )

    loaded = await _load_upload_content(
        device=device, parsed=parsed, artifact_service=artifact_service
    )
    if isinstance(loaded, Fail):
        return loaded
    content_text = loaded

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cfg", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content_text)
            tmp_path = tmp.name

        device_type = connection_device_type(device, parsed.network_driver_override)
        result = await netmiko.upload_file(
            host=host,
            network_driver=device.network_driver,
            platform=device.platform,
            username=username,
            password=password,
            local_path=tmp_path,
            dest_file=parsed.destination_filename,
            file_system=parsed.file_system,
            overwrite=parsed.overwrite,
            inline_transfer=parsed.inline_transfer,
            socket_timeout=parsed.socket_timeout,
            device_type=device_type,
            credential_reference=parsed.credential_reference,
        )
    finally:
        if tmp_path:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    updated_command_results, failed_transfer = record_transfer(
        device=device,
        node_id=node_id,
        command="upload-config",
        result=result,
        ok_summary=(
            f"uploaded {parsed.destination_filename} to {parsed.file_system} "
            f"(transferred={result.file_transferred}, verified={result.file_verified})"
        ),
        default_error="Config upload failed",
    )
    if failed_transfer is not None:
        return failed_transfer

    if parsed.verify_content:
        (
            verify_ok,
            verify_command_result,
            verify_message,
            verify_failure,
        ) = await _verify_uploaded_content(
            host=host,
            device=device,
            node_id=node_id,
            parsed=parsed,
            content_text=content_text,
            username=username,
            password=password,
            netmiko=netmiko,
            device_type=device_type,
        )
        updated_command_results[node_id] = [
            *updated_command_results[node_id],
            verify_command_result,
        ]
        if not verify_ok:
            return Fail(
                "verify_failed",
                verify_message or "Content verification failed",
                verify_failure,
                device=device.model_copy(update={"command_results": updated_command_results}),
            )

    enriched = device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "command_results": updated_command_results,
        }
    )
    return enriched


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    parsed = replace(
        _parse_upload_config(config),
        credential_reference=resolve_config_reference(
            config,
            source_key="credential_source",
            param_key="credential_param",
            literal_key="credential_reference",
            run_inputs=run.run_inputs,
        ),
    )

    db = require_session(run, "upload-config")
    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)

    run_id = log_run_id(run)
    total = len(context.devices)
    logger.info(
        "upload-config started run_id=%s node_id=%s devices=%d content_source=%s destination=%s%s",
        run_id,
        node_id,
        total,
        parsed.content_source,
        parsed.file_system,
        parsed.destination_filename,
    )

    async def _work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _upload_on_device(
            device_id=device_id,
            device=device,
            node_id=node_id,
            parsed=parsed,
            username=username,
            password=password,
            netmiko=netmiko,
            artifact_service=artifact_service,
        )

    # Connect/auth/SCP errors and artifact I/O fail that device only (the runner's boundary).
    batch = await run_per_device(
        context, _work, node_id=node_id, step_id=_STEP_ID, log_label=_STEP_ID
    )
    logger.info(
        "upload-config finished success=%d failure=%d run_id=%s",
        len(batch.ok),
        len(batch.failed),
        run_id,
    )
    return upload_outcomes(context, batch, noun="config")
