"""Executor for the run-command step.

Config parsing lives in ``parsing``, the per-device work in ``exec_mode`` / ``config_mode``, the
TextFSM/Genie normalisation in ``enrichment``. This module resolves credentials and dispatches.
"""

from __future__ import annotations

import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_session import require_session
from workflow_steps.run_command.config_mode import run_config_mode
from workflow_steps.run_command.enrichment import enrich_with_genie, enrich_with_textfsm
from workflow_steps.run_command.exec_mode import run_exec_mode
from workflow_steps.run_command.parsing import ParsedRunCommandConfig, parse_run_command_config

logger = logging.getLogger(__name__)


def _outcomes(
    context: WorkflowContext,
    succeeded: dict[str, DeviceContext],
    failed: dict[str, DeviceContext],
    command_count: int,
) -> list[StepOutcome]:
    return build_outcomes(
        context,
        succeeded,
        failed,
        success_summary=f"ran {command_count} command(s) on {len(succeeded)} device(s)",
        failure_summary=f"{len(failed)} device(s) failed",
    )


def _log_start(run_id: Any, total: int, parsed: ParsedRunCommandConfig) -> None:
    logger.info(
        "run-command run_id=%s devices=%d credential=%s mode=%s commands=%d parser=%s "
        "override=%s read_timeout=%d write_config=%s auto_confirm_prompts=%s dry_run=%s",
        run_id,
        total,
        parsed.credential_reference,
        parsed.execution_mode,
        len(parsed.commands),
        parsed.parser_mode,
        parsed.network_driver_override,
        parsed.read_timeout,
        parsed.write_config_after_execution,
        parsed.auto_confirm_prompts,
        parsed.dry_run,
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
    parsed = parse_run_command_config(config, run.run_inputs)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, "run-command")

    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)
    _log_start(log_run_id(run), total, parsed)
    if parsed.execution_mode == "config_mode":
        success_devices, failed_devices = await run_config_mode(
            context=context,
            node_id=node_id,
            run_id=log_run_id(run),
            parsed=parsed,
            username=username,
            password=password,
            netmiko=netmiko,
            artifact_service=artifact_service,
        )
        logger.info(
            "run-command finished mode=config_mode success=%d failure=%d run_id=%s",
            len(success_devices),
            len(failed_devices),
            log_run_id(run),
        )
        return _outcomes(context, success_devices, failed_devices, len(parsed.commands))

    success_devices, failed_devices, raw_outputs_by_device = await run_exec_mode(
        context=context,
        node_id=node_id,
        run_id=log_run_id(run),
        parsed=parsed,
        username=username,
        password=password,
        netmiko=netmiko,
        artifact_service=artifact_service,
    )

    if parsed.parser_mode == "textfsm":
        success_devices = enrich_with_textfsm(
            success_devices=success_devices,
            raw_outputs_by_device=raw_outputs_by_device,
            parsed_output_key=parsed.parsed_output_key,
            run_id=log_run_id(run),
        )
    elif parsed.parser_mode == "genie":
        success_devices = await enrich_with_genie(
            success_devices=success_devices,
            raw_outputs_by_device=raw_outputs_by_device,
            pyats_source_id=parsed.pyats_source_id,
            parsed_output_key=parsed.parsed_output_key,
            network_driver_override=parsed.network_driver_override,
            db=db,
            run_id=log_run_id(run),
        )

    logger.info(
        "run-command returning %d/%d devices mode=exec_mode run_id=%s",
        len(success_devices),
        total,
        log_run_id(run),
    )
    return _outcomes(context, success_devices, failed_devices, len(parsed.commands))
