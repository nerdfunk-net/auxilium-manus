"""Executor for the deploy-rendered-template step."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

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
from services.network.netmiko.connection import RetryPolicy
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool
from workflow_steps.common.content_resolver import list_exportable_content
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.failure_records import INVALID_INPUT, MISSING_DATA
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.retry_config import parse_retry_backoff_seconds
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_param_reference import resolve_config_reference
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_bool_flag, record_dry_run
from workflow_steps.deploy_rendered_template.config import get_config

logger = logging.getLogger(__name__)

_STEP_ID = "deploy-rendered-template"
_EXECUTION_MODES = {"config_mode", "exec_mode"}


@dataclass(frozen=True)
class _ParsedDeployConfig:
    credential_reference: str
    source_step_node_id: str
    parsed_output_key: str | None
    network_driver_override: str | None
    execution_mode: str
    write_config_after_execution: bool
    read_timeout: int
    auto_confirm_prompts: bool
    fail_on_cli_error: bool
    dry_run: bool
    retry: RetryPolicy


def _parse_execution_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("execution_mode") or get_config()["execution_mode"]).strip().lower()
    if mode not in _EXECUTION_MODES:
        raise ValueError(
            f"deploy-rendered-template: execution_mode must be one of {sorted(_EXECUTION_MODES)}"
        )
    return mode


def _parse_deploy_config(config: dict[str, Any]) -> _ParsedDeployConfig:
    source_step_node_id = str(config.get("source_step_node_id") or "").strip()
    if not source_step_node_id:
        raise ValueError("deploy-rendered-template: source_step_node_id is required")

    return _ParsedDeployConfig(
        credential_reference=str(config.get("credential_reference") or "").strip(),
        source_step_node_id=source_step_node_id,
        parsed_output_key=str(config.get("parsed_output_key") or "").strip() or None,
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        execution_mode=_parse_execution_mode(config),
        write_config_after_execution=parse_bool_flag(config, "write_config_after_execution"),
        read_timeout=parse_read_timeout(
            config, step_id=_STEP_ID, default=get_config()["read_timeout"]
        ),
        auto_confirm_prompts=parse_bool_flag(config, "auto_confirm_prompts"),
        fail_on_cli_error=parse_bool_flag(config, "fail_on_cli_error", default=True),
        dry_run=parse_bool_flag(config, "dry_run"),
        retry=parse_retry_backoff_seconds(config, step_id=_STEP_ID),
    )


async def _load_deploy_commands(
    *,
    device: DeviceContext,
    parsed: _ParsedDeployConfig,
    artifact_service: ArtifactService,
) -> list[str] | Fail:
    items = list_exportable_content(
        device,
        content_source="rendered_template",
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
    )
    if not items:
        return Fail(
            "rendered_template_missing",
            "No rendered template found for the configured source step",
            failure=MISSING_DATA,
        )
    rendered_text = await artifact_service.resolve(items[0].artifact_ref)
    # Split on "\n" only: the template renderer rejects every other line separator inside values,
    # so the two sides cannot disagree about where a command ends.
    commands = [line.rstrip("\r") for line in rendered_text.split("\n") if line.strip()]
    if not commands:
        return Fail(
            "empty_rendered_template",
            "Rendered template produced no commands",
            failure=MISSING_DATA,
        )
    return commands


async def _run_deploy_config(
    *,
    host: str,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    run_id: Any,
    parsed: _ParsedDeployConfig,
    username: str,
    password: str,
    commands: list[str],
    netmiko: NetmikoService,
) -> Any:
    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=parsed.network_driver_override,
    )
    result = await netmiko.deploy_config(
        host=host,
        network_driver=device.network_driver,
        platform=device.platform,
        username=username,
        password=password,
        commands=commands,
        mode=parsed.execution_mode,
        write_config=parsed.write_config_after_execution,
        device_type=device_type,
        read_timeout=parsed.read_timeout,
        auto_confirm_prompts=parsed.auto_confirm_prompts,
        fail_on_cli_error=parsed.fail_on_cli_error,
        credential_reference=parsed.credential_reference,
        retry=parsed.retry,
    )
    if result.confirmed_prompts:
        logger.warning(
            "deploy-rendered-template auto-confirmed %d prompt(s) run_id=%s "
            "node_id=%s device_id=%s commands=%s",
            len(result.confirmed_prompts),
            run_id,
            node_id,
            device_id,
            result.confirmed_prompts,
        )
    return result


async def _store_deploy_command_results(
    *,
    result: Any,
    commands: list[str],
    device_id: str,
    node_id: str,
    context_run_id: str,
    parsed: _ParsedDeployConfig,
    artifact_service: ArtifactService,
) -> list[CommandResult]:
    step_results: list[CommandResult] = []
    output_ref = await artifact_service.store(
        content=result.config_output,
        kind="command_output",
        device_id=device_id,
        run_id=context_run_id,
    )
    summary = f"{len(commands)} line(s) deployed ({parsed.execution_mode})"
    if result.confirmed_prompts:
        summary += f" · {len(result.confirmed_prompts)} confirmation prompt(s) auto-confirmed"
    step_results.append(
        CommandResult(
            node_id=node_id,
            command="deploy-rendered-template",
            success=result.success,
            output_ref=output_ref,
            summary=summary,
        )
    )
    if result.session_log:
        session_log_ref = await artifact_service.store(
            content=result.session_log,
            kind="netmiko_session_log",
            device_id=device_id,
            run_id=context_run_id,
        )
        step_results.append(
            CommandResult(
                node_id=node_id,
                command="netmiko-session-log",
                success=False,
                output_ref=session_log_ref,
                summary=(
                    "Raw Netmiko session log captured up to the failure — inspect "
                    "for confirmation prompts or unexpected CLI output that stalled "
                    "pattern detection"
                ),
            )
        )
    if result.save_output is not None:
        save_ref = await artifact_service.store(
            content=result.save_output,
            kind="command_output",
            device_id=device_id,
            run_id=context_run_id,
        )
        step_results.append(
            CommandResult(
                node_id=node_id,
                command="copy running-config startup-config",
                success=True,
                output_ref=save_ref,
                summary="running-config saved to startup-config",
            )
        )
    return step_results


def _apply_deploy_result(
    *,
    device: DeviceContext,
    node_id: str,
    result: Any,
    step_results: list[CommandResult],
) -> DeviceContext | Fail:
    updated_command_results = dict(device.command_results)
    updated_command_results[node_id] = step_results
    recorded = device.model_copy(update={"command_results": updated_command_results})
    if not result.success:
        return Fail(
            "deploy_failed",
            result.error or "Deploying rendered template failed",
            getattr(result, "failure", None),
            device=recorded,
        )
    return recorded.model_copy(update={"status": DeviceStatus.OK})


async def _deploy_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str,
    parsed: _ParsedDeployConfig,
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

    loaded = await _load_deploy_commands(
        device=device, parsed=parsed, artifact_service=artifact_service
    )
    if isinstance(loaded, Fail):
        return loaded

    if parsed.dry_run:
        return record_dry_run(
            device=device,
            node_id=node_id,
            payload={
                "would_deploy": True,
                "execution_mode": parsed.execution_mode,
                "commands": loaded,
                "host": host,
                "write_config_after_execution": parsed.write_config_after_execution,
                "source_step_node_id": parsed.source_step_node_id,
            },
        )

    result = await _run_deploy_config(
        host=host,
        device=device,
        device_id=device_id,
        node_id=node_id,
        run_id=run_id,
        parsed=parsed,
        username=username,
        password=password,
        commands=loaded,
        netmiko=netmiko,
    )
    step_results = await _store_deploy_command_results(
        result=result,
        commands=loaded,
        device_id=device_id,
        node_id=node_id,
        context_run_id=context_run_id,
        parsed=parsed,
        artifact_service=artifact_service,
    )
    return _apply_deploy_result(
        device=device, node_id=node_id, result=result, step_results=step_results
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
    parsed = replace(
        _parse_deploy_config(config),
        credential_reference=resolve_config_reference(
            config,
            source_key="credential_source",
            param_key="credential_param",
            literal_key="credential_reference",
            run_inputs=run.run_inputs,
        ),
    )

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, "deploy-rendered-template")

    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "deploy-rendered-template started run_id=%s node_id=%s devices=%d credential=%s "
        "source=%s mode=%s write_config=%s override=%s read_timeout=%d "
        "auto_confirm_prompts=%s dry_run=%s",
        log_run_id(run),
        node_id,
        total,
        parsed.credential_reference,
        parsed.source_step_node_id,
        parsed.execution_mode,
        parsed.write_config_after_execution,
        parsed.network_driver_override,
        parsed.read_timeout,
        parsed.auto_confirm_prompts,
        parsed.dry_run,
    )

    async def _work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _deploy_on_device(
            device_id=device_id,
            device=device,
            node_id=node_id,
            run_id=log_run_id(run),
            context_run_id=context.run_id,
            parsed=parsed,
            username=username,
            password=password,
            netmiko=netmiko,
            artifact_service=artifact_service,
        )

    # Template, artifact and connection errors fail that device only (the runner's boundary).
    batch = await run_per_device(
        context, _work, node_id=node_id, step_id=_STEP_ID, log_label=_STEP_ID
    )

    logger.info(
        "deploy-rendered-template finished success=%d failure=%d run_id=%s",
        len(batch.ok),
        len(batch.failed),
        log_run_id(run),
    )
    return build_outcomes(
        context,
        batch.ok,
        batch.failed,
        success_summary=f"deployed rendered template to {len(batch.ok)} device(s)",
        failure_summary=f"{len(batch.failed)} device(s) failed",
    )
