"""Executor for the run-command step."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.orm import Session, object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
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
from services.network.pyats.platform import resolve_pyats_os
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.jinja_render import parse_output_key
from workflow_steps.common.run_param_reference import resolve_config_reference

logger = logging.getLogger(__name__)

_STEP_ID = "run-command"


def _default_config() -> dict[str, Any]:
    from workflow_steps.run_command.config import get_config

    return get_config()


def _parse_commands(config: dict[str, Any]) -> list[str]:
    raw = config.get("commands")
    if raw is None:
        raw = _default_config().get("commands", [])
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
        raise ValueError("run-command: commands must be a list of strings")
    commands = [str(command).strip() for command in raw if str(command).strip()]
    if not commands:
        raise ValueError("run-command: at least one command is required")
    return commands


_PARSER_MODES = frozenset({"none", "textfsm", "genie"})


def _parse_parser_mode(config: dict[str, Any]) -> str:
    """Which parser (if any) normalizes this step's command output.

    "textfsm" and "genie" are mutually exclusive: whichever is selected, the
    result lands inline at ``parsed.<parsed_output_key>.<command>`` in the same
    ``{"parsed": ..., "error": ...}`` shape (see ``_enrich_with_textfsm`` /
    ``_enrich_with_genie``), so a downstream step never needs to know which
    parser produced it.
    """
    raw = config.get("parser")
    if raw is None:
        raw = _default_config()["parser"]
    mode = str(raw).strip().lower()
    if mode not in _PARSER_MODES:
        raise ValueError(
            f"run-command: parser must be one of {sorted(_PARSER_MODES)}, got {mode!r}"
        )
    return mode


def _build_summary(*, content: str, use_textfsm: bool) -> str:
    if use_textfsm:
        try:
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return f"{len(parsed)} row(s) parsed"
        except json.JSONDecodeError:
            pass
    return f"{len(content.encode('utf-8'))} bytes"


def _fail_device(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    code: str,
    message: str,
    command_results: dict[str, list[CommandResult]] | None = None,
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=code,
        message=message,
    )
    update: dict[str, Any] = {
        "status": DeviceStatus.FAILED,
        "errors": [*device.errors, err],
    }
    if command_results is not None:
        update["command_results"] = command_results
    failed = device.model_copy(update=update)
    return device_id, failed, False


async def _run_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    context_run_id: str | None,
    commands: list[str],
    use_textfsm: bool,
    network_driver_override: str | None,
    username: str,
    password: str,
    credential_reference: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool, dict[str, str]]:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        dev_id, failed, ok = _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )
        return dev_id, failed, ok, {}

    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=network_driver_override,
    )

    try:
        result = await netmiko.send_commands(
            host=host,
            network_driver=device.network_driver,
            platform=device.platform,
            username=username,
            password=password,
            commands=commands,
            use_textfsm=use_textfsm,
            device_type=device_type,
            credential_reference=credential_reference,
        )

        step_results: list[CommandResult] = []
        raw_outputs: dict[str, str] = {}
        media_type = "application/json" if use_textfsm else "text/plain"
        for command in commands:
            output = result.command_outputs.get(command, "")
            raw_outputs[command] = output
            output_ref = await artifact_service.store(
                content=output,
                kind="command_output",
                device_id=device_id,
                run_id=context_run_id,
                media_type=media_type,
            )
            step_results.append(
                CommandResult(
                    node_id=node_id,
                    command=command,
                    success=result.success,
                    output_ref=output_ref,
                    summary=_build_summary(content=output, use_textfsm=use_textfsm),
                )
            )

        updated_command_results = dict(device.command_results)
        updated_command_results[node_id] = step_results

        if not result.success:
            dev_id, failed, ok = _fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="command_failed",
                message=result.error or "Command execution failed",
                command_results=updated_command_results,
            )
            return dev_id, failed, ok, {}

        enriched = device.model_copy(
            update={
                "status": DeviceStatus.OK,
                "command_results": updated_command_results,
            }
        )
        return device_id, enriched, True, raw_outputs
    except Exception as exc:
        dev_id, failed, ok = _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
        )
        return dev_id, failed, ok, {}


async def _run_on_device_logged(
    *,
    index: int,
    device_id: str,
    device: DeviceContext,
    total: int,
    run_id: Any,
    node_id: str,
    context_run_id: str | None,
    commands: list[str],
    use_textfsm: bool,
    network_driver_override: str | None,
    username: str,
    password: str,
    credential_reference: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool, dict[str, str]]:
    host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
    logger.info(
        "run-command device %d/%d id=%s host=%s: connecting run_id=%s",
        index,
        total,
        device_id,
        host,
        run_id,
    )
    result = await _run_on_device(
        device_id=device_id,
        device=device,
        node_id=node_id,
        context_run_id=context_run_id,
        commands=commands,
        use_textfsm=use_textfsm,
        network_driver_override=network_driver_override,
        username=username,
        password=password,
        credential_reference=credential_reference,
        netmiko=netmiko,
        artifact_service=artifact_service,
    )
    _, _, ok, _ = result
    logger.info(
        "run-command device %d/%d id=%s host=%s: %s run_id=%s",
        index,
        total,
        device_id,
        host,
        "ok" if ok else "failed",
        run_id,
    )
    return result


def _partition_device_results(
    results: list[tuple[str, DeviceContext, bool, dict[str, str]]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext], dict[str, dict[str, str]]]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    raw_outputs_by_device: dict[str, dict[str, str]] = {}
    for device_id, updated_device, ok, raw_outputs in results:
        if ok:
            success_devices[device_id] = updated_device
            raw_outputs_by_device[device_id] = raw_outputs
        else:
            failed_devices[device_id] = updated_device
    return success_devices, failed_devices, raw_outputs_by_device


def _enrich_with_textfsm(
    *,
    success_devices: dict[str, DeviceContext],
    raw_outputs_by_device: dict[str, dict[str, str]],
    parsed_output_key: str,
    run_id: Any,
) -> dict[str, DeviceContext]:
    """Normalize netmiko's TextFSM output into the same inline shape Genie
    enrichment uses (``parsed.<parsed_output_key>.<command> = {"parsed", "error"}``),
    so a downstream step reads structured command output the same way
    regardless of which parser produced it.

    Non-fatal per command, matching Genie: netmiko falls back to returning the
    raw device text unchanged when no TextFSM template matches a command, so
    that command's ``output`` isn't valid JSON here -- record it as an error
    on that one command instead of failing the whole device.
    """
    enriched: dict[str, DeviceContext] = dict(success_devices)
    ok_count = 0
    error_count = 0
    for device_id, device in success_devices.items():
        raw_outputs = raw_outputs_by_device.get(device_id) or {}
        if not raw_outputs:
            continue
        parsed_entry: dict[str, Any] = {}
        for command, output in raw_outputs.items():
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                parsed_entry[command] = {
                    "parsed": None,
                    "error": "TextFSM did not match this command's output (no template found)",
                }
                error_count += 1
                continue
            parsed_entry[command] = {"parsed": data, "error": None}
            ok_count += 1
        parsed = dict(device.parsed)
        parsed[parsed_output_key] = parsed_entry
        enriched[device_id] = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
            }
        )

    logger.info(
        "run-command textfsm parsing finished run_id=%s devices=%d commands_ok=%d "
        "commands_error=%d",
        run_id,
        len(enriched),
        ok_count,
        error_count,
    )
    return enriched


async def _enrich_with_genie(
    *,
    success_devices: dict[str, DeviceContext],
    raw_outputs_by_device: dict[str, dict[str, str]],
    pyats_source_id: str,
    parsed_output_key: str,
    network_driver_override: str | None,
    db: Session,
    run_id: Any,
) -> dict[str, DeviceContext]:
    """Genie-parse each device's already-fetched raw output via the pyATS shim.

    Non-fatal by design: a device whose raw command execution already
    succeeded must not become FAILED just because Genie infrastructure is
    unreachable or has no parser for a given command -- see "Chosen design"
    in the plan this implements.
    """
    payload: dict[str, dict[str, Any]] = {}
    for device_id, device in success_devices.items():
        raw_outputs = raw_outputs_by_device.get(device_id) or {}
        if not raw_outputs:
            continue
        os_name = resolve_pyats_os(
            network_driver=device.network_driver,
            platform=device.platform,
            override=network_driver_override,
        )
        payload[device_id] = {
            "os": os_name,
            "commands": [
                {"command": command, "output": output} for command, output in raw_outputs.items()
            ],
        }

    if not payload:
        return success_devices

    try:
        credentials = PyATSSourceConfigService(db).resolve_credentials(pyats_source_id)
        shim = service_factory.get_pyats_app_service()
        response = await shim.parse_batch(credentials, devices=payload)
    except (PyATSSourceNotFoundError, PyATSValidationError, PyATSAPIError) as exc:
        logger.warning(
            "run-command genie parsing unavailable, skipping enrichment run_id=%s error=%s",
            run_id,
            exc,
        )
        return success_devices

    raw_results: dict[str, Any] = response.get("results") or {}
    enriched: dict[str, DeviceContext] = dict(success_devices)
    ok_count = 0
    error_count = 0
    for device_id, device_result in raw_results.items():
        device = enriched.get(device_id)
        if device is None:
            continue
        commands = device_result.get("commands") or {}
        parsed_entry: dict[str, Any] = {}
        for command, entry in commands.items():
            parsed_entry[command] = {"parsed": entry.get("parsed"), "error": entry.get("error")}
            if entry.get("error"):
                error_count += 1
            else:
                ok_count += 1
        parsed = dict(device.parsed)
        parsed[parsed_output_key] = parsed_entry
        enriched[device_id] = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
            }
        )

    logger.info(
        "run-command genie parsing finished run_id=%s devices=%d commands_ok=%d commands_error=%d",
        run_id,
        len(raw_results),
        ok_count,
        error_count,
    )
    return enriched


def _build_outcomes(
    *,
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
    command_count: int,
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"ran {command_count} command(s) on {len(success_devices)} device(s)",
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
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    credential_reference = resolve_config_reference(
        config,
        source_key="credential_source",
        param_key="credential_param",
        literal_key="credential_reference",
        run_inputs=run.run_inputs,
    )
    commands = _parse_commands(config)
    parser_mode = _parse_parser_mode(config)
    use_textfsm = parser_mode == "textfsm"
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None

    pyats_source_id = str(config.get("pyats_source_id") or "").strip()
    parsed_output_key = ""
    if parser_mode != "none":
        parsed_output_key = parse_output_key(
            config.get("parsed_output_key") or _default_config()["parsed_output_key"]
        )
    if parser_mode == "genie" and not pyats_source_id:
        raise ValueError("run-command: pyats_source_id is required when parser is 'genie'")

    db = object_session(run)
    if db is None:
        raise RuntimeError("run-command: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "run-command run_id=%s devices=%d credential=%s commands=%d parser=%s override=%s",
        run.id,
        total,
        credential_reference,
        len(commands),
        parser_mode,
        network_driver_override,
    )

    results = await asyncio.gather(
        *[
            _run_on_device_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run.id,
                node_id=node_id,
                context_run_id=context.run_id,
                commands=commands,
                use_textfsm=use_textfsm,
                network_driver_override=network_driver_override,
                username=username,
                password=password,
                credential_reference=credential_reference,
                netmiko=netmiko,
                artifact_service=artifact_service,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )

    success_devices, failed_devices, raw_outputs_by_device = _partition_device_results(results)

    if parser_mode == "textfsm":
        success_devices = _enrich_with_textfsm(
            success_devices=success_devices,
            raw_outputs_by_device=raw_outputs_by_device,
            parsed_output_key=parsed_output_key,
            run_id=run.id,
        )
    elif parser_mode == "genie":
        success_devices = await _enrich_with_genie(
            success_devices=success_devices,
            raw_outputs_by_device=raw_outputs_by_device,
            pyats_source_id=pyats_source_id,
            parsed_output_key=parsed_output_key,
            network_driver_override=network_driver_override,
            db=db,
            run_id=run.id,
        )

    logger.info(
        "run-command returning %d/%d devices run_id=%s",
        len(success_devices),
        total,
        run.id,
    )

    return _build_outcomes(
        context=context,
        success_devices=success_devices,
        failed_devices=failed_devices,
        command_count=len(commands),
    )
