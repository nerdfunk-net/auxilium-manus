"""Executor for the get-device-configs step."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.connection import DEFAULT_CONFIG_READ_TIMEOUT, RetryPolicy
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.read_timeout import parse_read_timeout
from workflow_steps.common.retry_config import parse_retry_backoff_seconds
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_param_reference import resolve_config_reference
from workflow_steps.common.run_session import require_session
from workflow_steps.get_device_configs.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-device-configs"
_CONFIG_FORMATS = frozenset({"running", "startup", "both"})


@dataclass(frozen=True)
class _ParsedConfig:
    config_format: str
    read_timeout: int
    retry: RetryPolicy


def _config_targets(config_format: str) -> tuple[bool, bool]:
    normalized = config_format.strip().lower()
    if normalized == "running":
        return True, False
    if normalized == "startup":
        return False, True
    return True, True


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    config_format = (
        str(config.get("config_format") or get_config()["config_format"]).strip().lower()
    )
    if config_format not in _CONFIG_FORMATS:
        raise ValueError(
            f"get-device-configs: config_format must be one of {sorted(_CONFIG_FORMATS)}"
        )
    return _ParsedConfig(
        config_format=config_format,
        read_timeout=parse_read_timeout(
            config, step_id=_STEP_ID, default=DEFAULT_CONFIG_READ_TIMEOUT
        ),
        retry=parse_retry_backoff_seconds(config, step_id=_STEP_ID),
    )


async def _fetch_device(
    *,
    device_id: str,
    device: DeviceContext,
    context_run_id: str,
    parsed: _ParsedConfig,
    credential_reference: str,
    username: str,
    password: str,
    netmiko: NetmikoService,
    artifact_service: ArtifactService,
) -> DeviceContext | Fail:
    """One device. An exception that escapes is turned into a failed device by the runner."""
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return Fail(
            "missing_host",
            f"Device {device_id} has no hostname or primary IP",
            failure=INVALID_INPUT,
        )

    include_running, include_startup = _config_targets(parsed.config_format)
    result = await netmiko.get_configs(
        host=host,
        network_driver=device.network_driver,
        platform=device.platform,
        username=username,
        password=password,
        include_running=include_running,
        include_startup=include_startup,
        credential_reference=credential_reference,
        read_timeout=parsed.read_timeout,
        retry=parsed.retry,
    )
    if not result.success:
        return Fail(
            "config_retrieval_failed",
            result.error or "Config retrieval failed",
            result.failure,
        )

    updates: dict[str, Any] = {
        "status": DeviceStatus.OK,
        "capabilities": set(device.capabilities),
    }
    if include_running and result.running_config is not None:
        updates["running_config_ref"] = await artifact_service.store(
            content=result.running_config,
            kind="running_config",
            device_id=device_id,
            run_id=context_run_id,
        )
        updates["capabilities"] = updates["capabilities"] | {Capability.RUNNING_CONFIG}
    if include_startup and result.startup_config is not None:
        updates["startup_config_ref"] = await artifact_service.store(
            content=result.startup_config,
            kind="startup_config",
            device_id=device_id,
            run_id=context_run_id,
        )
        updates["capabilities"] = updates["capabilities"] | {Capability.STARTUP_CONFIG}
    return device.model_copy(update=updates)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    parsed = _parse_config(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, "get-device-configs")

    credential_reference = resolve_config_reference(
        config,
        source_key="credential_source",
        param_key="credential_param",
        literal_key="credential_reference",
        run_inputs=run.run_inputs,
    )
    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "get-device-configs run_id=%s devices=%d credential=%s format=%s",
        log_run_id(run),
        total,
        credential_reference,
        parsed.config_format,
    )

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _fetch_device(
            device_id=device_id,
            device=device,
            context_run_id=context.run_id,
            parsed=parsed,
            credential_reference=credential_reference,
            username=username,
            password=password,
            netmiko=netmiko,
            artifact_service=artifact_service,
        )

    batch = await run_per_device(
        context, work, node_id=node_id, step_id=_STEP_ID, log_label=_STEP_ID
    )
    logger.info(
        "get-device-configs returning %d/%d devices run_id=%s",
        len(batch.ok),
        total,
        log_run_id(run),
    )
    return build_outcomes(context, batch.ok, batch.failed)
