"""Executor for the upload-config step."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import tempfile
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool
from workflow_steps.common.content_resolver import CONTENT_SOURCES, list_exportable_content
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.run_param_reference import resolve_config_reference

logger = logging.getLogger(__name__)

_STEP_ID = "upload-config"
_SOURCE_STEP_ID_EXEMPT = frozenset({"running_config", "startup_config", "latest_command_output"})
_MIN_SOCKET_TIMEOUT = 5
_MAX_SOCKET_TIMEOUT = 300


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


def _parse_bool(config: dict[str, Any], key: str) -> bool:
    value = config.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_socket_timeout(config: dict[str, Any]) -> int:
    raw = config.get("socket_timeout")
    if raw in (None, ""):
        raw = 10
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("upload-config: socket_timeout must be an integer") from exc
    if not (_MIN_SOCKET_TIMEOUT <= value <= _MAX_SOCKET_TIMEOUT):
        raise ValueError(
            f"upload-config: socket_timeout must be between {_MIN_SOCKET_TIMEOUT} "
            f"and {_MAX_SOCKET_TIMEOUT} seconds"
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
        destination_filename=destination_filename,
        file_system=file_system,
        overwrite=_parse_bool(config, "overwrite"),
        inline_transfer=_parse_bool(config, "inline_transfer"),
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        socket_timeout=_parse_socket_timeout(config),
    )


def _fail_device(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    code: str,
    message: str,
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=code,
        message=message,
    )
    failed = device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [*device.errors, err],
        }
    )
    return device_id, failed, False


async def _load_upload_content(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    parsed: _ParsedUploadConfig,
    artifact_service: ArtifactService,
) -> str | tuple[str, DeviceContext, bool]:
    items = list_exportable_content(
        device,
        content_source=parsed.content_source,
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
    )
    if not items:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=f"{parsed.content_source}_missing",
            message=f"No {parsed.content_source} found for the configured source",
        )
    return await artifact_service.resolve(items[0].artifact_ref)


async def _upload_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    parsed: _ParsedUploadConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    del run_id  # kept for parity with sibling steps' _*_on_device signatures
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )

    loaded = await _load_upload_content(
        device=device,
        device_id=device_id,
        node_id=node_id,
        parsed=parsed,
        artifact_service=artifact_service,
    )
    if isinstance(loaded, tuple):
        return loaded
    content_text = loaded

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".cfg", delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content_text)
            tmp_path = tmp.name

        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=parsed.network_driver_override,
        )
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

    summary = (
        f"uploaded {parsed.destination_filename} to {parsed.file_system} "
        f"(transferred={result.file_transferred}, verified={result.file_verified})"
        if result.success
        else (result.error or "Config upload failed")
    )
    updated_command_results = dict(device.command_results)
    updated_command_results[node_id] = [
        CommandResult(
            node_id=node_id,
            command="upload-config",
            success=result.success,
            summary=summary,
        )
    ]

    if not result.success:
        err = DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code="upload_failed",
            message=result.error or "Config upload failed",
        )
        failed = device.model_copy(
            update={
                "status": DeviceStatus.FAILED,
                "errors": [*device.errors, err],
                "command_results": updated_command_results,
            }
        )
        return device_id, failed, False

    enriched = device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "command_results": updated_command_results,
        }
    )
    return device_id, enriched, True


async def _upload_on_device_logged(
    *,
    index: int,
    device_id: str,
    device: DeviceContext,
    total: int,
    run_id: Any,
    node_id: str,
    parsed: _ParsedUploadConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
    logger.info(
        "upload-config device %d/%d id=%s host=%s: connecting run_id=%s",
        index,
        total,
        device_id,
        host,
        run_id,
    )
    result = await _upload_on_device(
        device_id=device_id,
        device=device,
        node_id=node_id,
        run_id=run_id,
        parsed=parsed,
        username=username,
        password=password,
        netmiko=netmiko,
        artifact_service=artifact_service,
    )
    _, _, ok = result
    logger.info(
        "upload-config device %d/%d id=%s host=%s: %s run_id=%s",
        index,
        total,
        device_id,
        host,
        "ok" if ok else "failed",
        run_id,
    )
    return result


def _partition_device_results(
    results: list[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device
    return success_devices, failed_devices


def _build_upload_outcomes(
    *,
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"uploaded config to {len(success_devices)} device(s)",
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

    db = object_session(run)
    if db is None:
        raise RuntimeError("upload-config: WorkflowRun has no active DB session")
    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)

    run_id = run.id
    total = len(context.devices)
    logger.info(
        "upload-config started run_id=%s node_id=%s devices=%d content_source=%s "
        "destination=%s%s",
        run_id,
        node_id,
        total,
        parsed.content_source,
        parsed.file_system,
        parsed.destination_filename,
    )

    results = await asyncio.gather(
        *[
            _upload_on_device_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run_id,
                node_id=node_id,
                parsed=parsed,
                username=username,
                password=password,
                netmiko=netmiko,
                artifact_service=artifact_service,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    success_devices, failed_devices = _partition_device_results(results)
    logger.info(
        "upload-config finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run_id,
    )
    return _build_upload_outcomes(
        context=context, success_devices=success_devices, failed_devices=failed_devices
    )
