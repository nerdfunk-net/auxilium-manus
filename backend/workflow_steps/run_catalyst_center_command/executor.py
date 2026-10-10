"""Executor for the run-catalyst-center-command step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.catalyst_center import CatalystCenterCommandResult, CatalystCenterCommandStatus
from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
    CommandResult,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterValidationError,
)
from services.catalyst_center.common.output import clean_command_output
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.catalyst_center_targets import (
    build_outcomes,
    failed_device,
    resolve_source_credentials,
    split_targets,
)
from workflow_steps.common.jinja_render import JinjaTemplateError, parse_output_key
from workflow_steps.common.textfsm_parse import parse_with_textfsm

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

STEP_ID = "run-catalyst-center-command"
DEFAULT_TIMEOUT = 300
# The service polls the controller task for at most DEFAULT_TIMEOUT seconds, so a larger
# timeout could never be honoured.
MAX_TIMEOUT = 300
# Per-request device/command limits are undocumented; stay conservative.
DEVICES_PER_REQUEST = 20
MAX_COMMANDS = 20
MAX_PARALLEL_REQUESTS = 3
_SUMMARY_PREVIEW_CHARS = 80
_PARSER_MODES = frozenset({"none", "textfsm"})
DEFAULT_PARSED_OUTPUT_KEY = "parsed"


@dataclass(frozen=True)
class _ParsedConfig:
    commands: tuple[str, ...]
    timeout: int
    parser_mode: str
    parsed_output_key: str
    network_driver_override: str | None


def _parse_commands(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{STEP_ID}: commands must be a list of strings")
    commands = tuple(item.strip() for item in raw if item.strip())
    if not commands:
        raise ValueError(f"{STEP_ID}: at least one command is required")
    if len(commands) > MAX_COMMANDS:
        raise ValueError(f"{STEP_ID}: at most {MAX_COMMANDS} commands are allowed")
    if len(set(commands)) != len(commands):
        # Results come back keyed by command text, so a duplicate would collapse.
        raise ValueError(f"{STEP_ID}: commands must be unique")
    return commands


def _parse_timeout(raw: Any) -> int:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return DEFAULT_TIMEOUT
    value: Any = int(raw) if isinstance(raw, str) and raw.strip().isdecimal() else raw
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_TIMEOUT:
        raise ValueError(f"{STEP_ID}: timeout must be a whole number between 1 and {MAX_TIMEOUT}")
    return value


def _parse_parser_mode(raw: Any) -> str:
    mode = str(raw if raw is not None else "none").strip().lower()
    if mode not in _PARSER_MODES:
        raise ValueError(f"{STEP_ID}: parser must be one of {sorted(_PARSER_MODES)}, got {mode!r}")
    return mode


def _parse_output_key(raw: Any) -> str:
    try:
        return parse_output_key(raw or DEFAULT_PARSED_OUTPUT_KEY)
    except JinjaTemplateError as exc:
        raise ValueError(f"{STEP_ID}: parsed_output_key: {exc}") from exc


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    parser_mode = _parse_parser_mode(config.get("parser"))
    return _ParsedConfig(
        commands=_parse_commands(config.get("commands")),
        timeout=_parse_timeout(config.get("timeout")),
        parser_mode=parser_mode,
        parsed_output_key=_parse_output_key(config.get("parsed_output_key"))
        if parser_mode != "none"
        else "",
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
    )


def _summary(command_result: CatalystCenterCommandResult | None, cleaned: str) -> str:
    if command_result is None:
        return "no output returned"
    if command_result.status is not CatalystCenterCommandStatus.SUCCESS:
        return command_result.status.value
    first_line = next((line.strip() for line in cleaned.splitlines() if line.strip()), "")
    lines = len(cleaned.splitlines())
    preview = first_line[:_SUMMARY_PREVIEW_CHARS]
    return f"{lines} line(s) · {preview}" if preview else "empty output"


def _command_failure(
    results: dict[str, CatalystCenterCommandResult], commands: tuple[str, ...]
) -> FailureInfo:
    """Blocklisted wins over a plain failure: it is a different fix (the command itself)."""
    blocked = any(
        (r := results.get(c)) is not None and r.status is CatalystCenterCommandStatus.BLOCKLISTED
        for c in commands
    )
    if blocked:
        return FailureInfo(phase="command", kind="command_blocked", hint="check_command_syntax")
    return FailureInfo(phase="command", kind="command_error")


async def _record_device(
    *,
    device_id: str,
    device: DeviceContext,
    commands: tuple[str, ...],
    results: dict[str, CatalystCenterCommandResult],
    parsed: _ParsedConfig,
    node_id: str,
    run_id: str,
    artifact_service: ArtifactService,
) -> tuple[DeviceContext, bool]:
    step_results: list[CommandResult] = []
    problems: list[str] = []
    parsed_entry: dict[str, Any] = {}
    platform = parsed.network_driver_override or device.network_driver
    for command in commands:
        result = results.get(command)
        ok = result is not None and result.status is CatalystCenterCommandStatus.SUCCESS
        cleaned = clean_command_output(command, result.output) if result is not None else ""
        output_ref = None
        if result is not None:
            output_ref = await artifact_service.store(
                content=cleaned, kind="command_output", device_id=device_id, run_id=run_id
            )
        if ok and parsed.parser_mode == "textfsm":
            parsed_entry[command] = parse_with_textfsm(cleaned, command=command, platform=platform)
        if not ok:
            reason = result.status.value if result is not None else "no output returned"
            problems.append(f"'{command}': {reason}")
        step_results.append(
            CommandResult(
                node_id=node_id,
                command=command,
                success=ok,
                output_ref=output_ref,
                summary=_summary(result, cleaned),
            )
        )

    command_results = {**device.command_results, node_id: step_results}
    if problems:
        failed = failed_device(
            device,
            step_id=STEP_ID,
            node_id=node_id,
            code="command_failed",
            message="; ".join(problems),
            command_results=command_results,
            failure=_command_failure(results, commands),
        )
        return failed, False
    update: dict[str, Any] = {"status": DeviceStatus.OK, "command_results": command_results}
    if parsed.parser_mode != "none":
        update["parsed"] = {**device.parsed, parsed.parsed_output_key: parsed_entry}
        update["capabilities"] = device.capabilities | {Capability.PARSED}
    return device.model_copy(update=update), True


async def _run_chunk(
    *,
    chunk: dict[str, DeviceContext],
    credentials: CatalystCenterCredentials,
    parsed: _ParsedConfig,
    node_id: str,
    run_id: str,
    artifact_service: ArtifactService,
    gate: asyncio.Semaphore,
) -> dict[str, tuple[DeviceContext, bool]]:
    command_service = service_factory.build_catalyst_center_command_service(credentials)
    try:
        async with gate:
            results = await command_service.run_commands(
                list(chunk), list(parsed.commands), timeout=parsed.timeout
            )
    except (CatalystCenterValidationError, CatalystCenterAPIError, CatalystCenterAuthError) as exc:
        # Transport/controller failures fail this chunk's devices, not the whole step.
        logger.warning(
            "%s request failed run_id=%s node_id=%s devices=%d error=%s",
            STEP_ID,
            run_id,
            node_id,
            len(chunk),
            type(exc).__name__,
        )
        message = f"Catalyst Center request failed: {exc}"
        return {
            device_id: (
                failed_device(
                    device,
                    step_id=STEP_ID,
                    node_id=node_id,
                    code="catalyst_center_error",
                    message=message,
                    failure=exc.failure,
                ),
                False,
            )
            for device_id, device in chunk.items()
        }

    by_device: dict[str, dict[str, CatalystCenterCommandResult]] = {}
    for result in results:
        by_device.setdefault(result.device_id, {})[result.command] = result

    return {
        device_id: await _record_device(
            device_id=device_id,
            device=device,
            commands=parsed.commands,
            results=by_device.get(device_id, {}),
            parsed=parsed,
            node_id=node_id,
            run_id=run_id,
            artifact_service=artifact_service,
        )
        for device_id, device in chunk.items()
    }


def _chunks(devices: dict[str, DeviceContext]) -> list[dict[str, DeviceContext]]:
    items = list(devices.items())
    return [
        dict(items[start : start + DEVICES_PER_REQUEST])
        for start in range(0, len(items), DEVICES_PER_REQUEST)
    ]


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # commands run on the controller, not over SSH

    parsed = _parse_config(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{STEP_ID}: WorkflowRun has no active DB session")

    split = split_targets(context.devices, step_id=STEP_ID, node_id=node_id)
    credentials = resolve_source_credentials(db, list(split.by_source), step_id=STEP_ID)

    total = len(context.devices)
    logger.info(
        "%s started run_id=%s node_id=%s devices=%d commands=%d",
        STEP_ID,
        context.run_id,
        node_id,
        total,
        len(parsed.commands),
    )

    gate = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)
    chunk_results = await asyncio.gather(
        *[
            _run_chunk(
                chunk=chunk,
                credentials=credentials[source_id],
                parsed=parsed,
                node_id=node_id,
                run_id=context.run_id,
                artifact_service=artifact_service,
                gate=gate,
            )
            for source_id, devices in split.by_source.items()
            for chunk in _chunks(devices)
        ]
    )

    succeeded: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = dict(split.rejected)
    for chunk_result in chunk_results:
        for device_id, (device, ok) in chunk_result.items():
            (succeeded if ok else failed)[device_id] = device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        STEP_ID,
        len(succeeded),
        len(failed),
        context.run_id,
    )
    return build_outcomes(context, succeeded, failed)
