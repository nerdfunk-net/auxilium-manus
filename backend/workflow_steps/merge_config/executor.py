"""Executor for the merge-config step.

Applies a *partial* configuration file already staged on a device (e.g. by an
upstream Upload Config step) by issuing Cisco IOS
``copy <source_filename> running-config`` over SSH and answering the
``Destination filename [running-config]? `` prompt with Enter. The file's
commands are layered onto the running config in the device's non-interactive
batch mode.

Unlike configure-replace-config (complete-config replace via the pyATS shim,
with a rollback timer) this is an additive merge over SSH with no rollback:
whatever the file contains is applied on top of the running config. It always
answers the prompt -- there is no opt-in checkbox.

Reuses the Run Command backend end to end: NetmikoService / DeviceSessionPool,
``resolve_config_reference`` + ``resolve_ssh_credential`` for credentials,
``resolve_connection_device_type`` for the Netmiko device type, ArtifactService
for the stored transcript, and the success/failure StepOutcome shape.
"""

from __future__ import annotations

import logging
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
from services.network.netmiko.connection import RetryPolicy
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from services.network.netmiko.session_pool import DeviceSessionPool
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.retry_config import parse_retry_backoff_seconds
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_param_reference import resolve_config_reference

logger = logging.getLogger(__name__)

_STEP_ID = "merge-config"
_ARTIFACT_KIND = "command_output"


def _default_config() -> dict[str, Any]:
    from workflow_steps.merge_config.config import get_config

    return get_config()


@dataclass(frozen=True)
class _ParsedMergeConfig:
    credential_reference: str
    source_filename: str
    network_driver_override: str | None
    read_timeout: int
    retry: RetryPolicy


def _parse_merge_config(config: dict[str, Any]) -> _ParsedMergeConfig:
    source_filename = str(config.get("source_filename") or "").strip()
    if not source_filename:
        raise ValueError(f"{_STEP_ID}: source_filename is required")
    return _ParsedMergeConfig(
        credential_reference="",
        source_filename=source_filename,
        network_driver_override=str(config.get("network_driver_override") or "").strip() or None,
        read_timeout=parse_read_timeout(
            config, step_id=_STEP_ID, default=_default_config()["read_timeout"]
        ),
        retry=parse_retry_backoff_seconds(config, step_id=_STEP_ID),
    )


async def _merge_on_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: Any,
    context_run_id: str,
    parsed: _ParsedMergeConfig,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> DeviceContext | Fail:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return Fail("missing_host", f"Device {device_id} has no hostname or primary IP")

    command = f"copy {parsed.source_filename} running-config"

    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=parsed.network_driver_override,
    )
    result = await netmiko.merge_config(
        host=host,
        network_driver=device.network_driver,
        platform=device.platform,
        username=username,
        password=password,
        source_filename=parsed.source_filename,
        device_type=device_type,
        credential_reference=parsed.credential_reference,
        read_timeout=parsed.read_timeout,
        retry=parsed.retry,
    )

    answered = list(result.confirmed_prompts)
    if answered:
        logger.warning(
            "%s auto-answered %d interactive prompt(s) run_id=%s node_id=%s device_id=%s cues=%s",
            _STEP_ID,
            len(answered),
            run_id,
            node_id,
            device_id,
            answered,
        )

    output = result.output or ""
    output_ref = await artifact_service.store(
        content=output,
        kind=_ARTIFACT_KIND,
        device_id=device_id,
        run_id=context_run_id,
        media_type="text/plain",
    )
    summary = f"{len(output.encode('utf-8'))} bytes"
    if answered:
        summary += f" · {len(answered)} interactive prompt(s) auto-answered"

    step_result = CommandResult(
        node_id=node_id,
        command=command,
        success=result.success,
        output_ref=output_ref,
        summary=summary,
    )
    updated_command_results = dict(device.command_results)
    updated_command_results[node_id] = [step_result]

    recorded = device.model_copy(update={"command_results": updated_command_results})
    if not result.success:
        return Fail(
            "merge_failed",
            result.error or f"{command!r} failed",
            result.failure,
            device=recorded,
        )
    return recorded.model_copy(update={"status": DeviceStatus.OK})


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
        _parse_merge_config(config),
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
    total = len(context.devices)

    logger.info(
        "%s run_id=%s devices=%d credential=%s source_filename=%s override=%s read_timeout=%d",
        _STEP_ID,
        log_run_id(run),
        total,
        parsed.credential_reference,
        parsed.source_filename,
        parsed.network_driver_override,
        parsed.read_timeout,
    )

    async def _work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _merge_on_device(
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

    # Connection and artifact errors fail that device only (the runner's boundary).
    batch = await run_per_device(
        context, _work, node_id=node_id, step_id=_STEP_ID, log_label=_STEP_ID
    )

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(batch.ok),
        len(batch.failed),
        log_run_id(run),
    )
    return build_outcomes(
        context,
        batch.ok,
        batch.failed,
        success_summary=(
            f"merged {parsed.source_filename} into running-config on {len(batch.ok)} device(s)"
        ),
        failure_summary=f"{len(batch.failed)} device(s) failed",
    )
