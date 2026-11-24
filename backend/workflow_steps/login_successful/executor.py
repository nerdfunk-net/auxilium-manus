"""Executor for the login-successful step."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
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
from services.workflow_context.node_result import set_node_result
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.device_outcomes import outcomes_from_buckets
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.partial_outcomes import device_error_from_exception
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_param_reference import resolve_config_reference

logger = logging.getLogger(__name__)

_OUTCOME_NAMES = ("success", "failure")
_STEP_ID = "login-successful"
_MISSING_HOST = FailureInfo(phase="connect", kind="bad_request", hint="check_hostname")
_NOT_ALIVE = FailureInfo(phase="connect", kind="ssh_error")


def _with_login_parsed(
    device: DeviceContext,
    *,
    node_id: str,
    login_ok: bool,
    host: str,
    credential_reference: str,
    error: str | None = None,
) -> DeviceContext:
    result: dict[str, Any] = {
        "kind": "login_result",
        "login_ok": login_ok,
        "host": host,
        "credential_reference": credential_reference,
    }
    if error is not None:
        result["error"] = error
    parsed = set_node_result(device.parsed, node_id, "login", result)
    return device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
        }
    )


def _login_failed(
    device: DeviceContext,
    *,
    node_id: str,
    host: str,
    credential_reference: str,
    code: str,
    message: str,
    failure: FailureInfo,
    error: str,
) -> Fail:
    """A failed login: the error is on the device and so is the result record in its bag.

    ``error`` is a closed code (never the text of a driver exception): downstream steps and the
    run viewer can read the bag.
    """
    marked = _with_login_parsed(
        device,
        node_id=node_id,
        login_ok=False,
        host=host,
        credential_reference=credential_reference,
        error=error,
    )
    return Fail(code, message, failure, device=marked)


async def _try_login(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    credential_reference: str,
    network_driver_override: str | None,
    username: str,
    password: str,
    netmiko: NetmikoService,
) -> DeviceContext | Fail:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return _login_failed(
            device,
            node_id=node_id,
            host="",
            credential_reference=credential_reference,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
            failure=_MISSING_HOST,
            error="missing_host",
        )

    try:
        # An unknown platform fails this device (UnsupportedPlatformError carries the failure).
        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=network_driver_override,
        )
        # Disposable probe login: does not touch any pooled session, so a
        # prior deploy session remains available for rollback on failure.
        alive = await netmiko.test_login(
            host=host,
            network_driver=device.network_driver,
            platform=device.platform,
            username=username,
            password=password,
            credential_reference=credential_reference,
            device_type=device_type,
        )
    except Exception as exc:
        error = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
        failure = error.failure or _NOT_ALIVE  # the helper always sets one
        return _login_failed(
            device,
            node_id=node_id,
            host=host,
            credential_reference=credential_reference,
            code=error.code,
            message=error.message,
            failure=failure,
            error=failure.kind,
        )
    if not alive:
        return _login_failed(
            device,
            node_id=node_id,
            host=host,
            credential_reference=credential_reference,
            code="login_failed",
            message="SSH session opened but is not alive",
            failure=_NOT_ALIVE,
            error="session_not_alive",
        )
    return _with_login_parsed(
        device.model_copy(update={"status": DeviceStatus.OK}),
        node_id=node_id,
        login_ok=True,
        host=host,
        credential_reference=credential_reference,
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
    del artifact_service

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    credential_reference = resolve_config_reference(
        config,
        source_key="credential_source",
        param_key="credential_param",
        literal_key="credential_reference",
        run_inputs=run.run_inputs,
    )
    network_driver_override = str(config.get("network_driver_override") or "").strip() or None

    db = object_session(run)
    if db is None:
        raise RuntimeError("login-successful: WorkflowRun has no active DB session")

    username, password = resolve_ssh_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    netmiko = NetmikoService(pool=device_sessions)
    total = len(context.devices)

    logger.info(
        "login-successful started run_id=%s node_id=%s devices=%d credential=%s override=%s",
        log_run_id(run),
        node_id,
        total,
        credential_reference,
        network_driver_override,
    )

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _try_login(
            device_id=device_id,
            device=device,
            node_id=node_id,
            credential_reference=credential_reference,
            network_driver_override=network_driver_override,
            username=username,
            password=password,
            netmiko=netmiko,
        )

    batch = await run_per_device(
        context, work, node_id=node_id, step_id=_STEP_ID, log_label=_STEP_ID
    )
    counts = {"success": len(batch.ok), "failure": len(batch.failed)}
    logger.info(
        "login-successful finished success=%d failure=%d run_id=%s",
        counts["success"],
        counts["failure"],
        log_run_id(run),
    )
    return outcomes_from_buckets(
        context,
        {"success": batch.ok, "failure": batch.failed},
        metadata={f"{node_id}.login_counts": counts},
    )
