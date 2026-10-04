"""Executor for the run-command step.

Config parsing lives in ``parsing``, the per-device work in ``exec_mode`` / ``config_mode``, the
TextFSM/Genie normalisation in ``enrichment``. This module resolves credentials and dispatches.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.run_param_reference import resolve_config_reference
from workflow_steps.run_command.config_mode import run_config_mode
from workflow_steps.run_command.enrichment import enrich_with_genie, enrich_with_textfsm
from workflow_steps.run_command.exec_mode import run_exec_mode
from workflow_steps.run_command.outcomes import build_outcomes
from workflow_steps.run_command.parsing import ParsedRunCommandConfig, parse_run_command_config

logger = logging.getLogger(__name__)


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
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    parsed = replace(
        parse_run_command_config(config),
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
        raise RuntimeError("run-command: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, parsed.credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)
    _log_start(run.id, total, parsed)
    run_kwargs: dict[str, Any] = {
        "context": context,
        "node_id": node_id,
        "run_id": run.id,
        "parsed": parsed,
        "username": username,
        "password": password,
        "netmiko": netmiko,
        "artifact_service": artifact_service,
    }

    if parsed.execution_mode == "config_mode":
        success_devices, failed_devices = await run_config_mode(**run_kwargs)
        logger.info(
            "run-command finished mode=config_mode success=%d failure=%d run_id=%s",
            len(success_devices),
            len(failed_devices),
            run.id,
        )
        return build_outcomes(
            context=context,
            success_devices=success_devices,
            failed_devices=failed_devices,
            command_count=len(parsed.commands),
        )

    success_devices, failed_devices, raw_outputs_by_device = await run_exec_mode(**run_kwargs)

    if parsed.parser_mode == "textfsm":
        success_devices = enrich_with_textfsm(
            success_devices=success_devices,
            raw_outputs_by_device=raw_outputs_by_device,
            parsed_output_key=parsed.parsed_output_key,
            run_id=run.id,
        )
    elif parsed.parser_mode == "genie":
        success_devices = await enrich_with_genie(
            success_devices=success_devices,
            raw_outputs_by_device=raw_outputs_by_device,
            pyats_source_id=parsed.pyats_source_id,
            parsed_output_key=parsed.parsed_output_key,
            network_driver_override=parsed.network_driver_override,
            db=db,
            run_id=run.id,
        )

    logger.info(
        "run-command returning %d/%d devices mode=exec_mode run_id=%s",
        len(success_devices),
        total,
        run.id,
    )
    return build_outcomes(
        context=context,
        success_devices=success_devices,
        failed_devices=failed_devices,
        command_count=len(parsed.commands),
    )
