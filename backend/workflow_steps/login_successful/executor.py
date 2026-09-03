"""Executor for the login-successful step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
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
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.run_param_reference import resolve_config_reference

logger = logging.getLogger(__name__)

_OUTCOME_NAMES = ("success", "failure")
_STEP_ID = "login-successful"


def _device_failure(
    device: DeviceContext, *, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def _with_login_parsed(
    device: DeviceContext,
    *,
    node_id: str,
    login_ok: bool,
    host: str,
    credential_reference: str,
    error: str | None = None,
) -> DeviceContext:
    parsed = dict(device.parsed)
    result: dict[str, Any] = {
        "kind": "login_result",
        "login_ok": login_ok,
        "host": host,
        "credential_reference": credential_reference,
    }
    if error is not None:
        result["error"] = error
    parsed[f"{node_id}.login"] = result
    return device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
        }
    )


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
) -> tuple[str, DeviceContext]:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        failed = _device_failure(
            device,
            node_id=node_id,
            code="missing_host",
            message=f"Device {device_id} has no hostname or primary IP",
        )
        return "failure", _with_login_parsed(
            failed,
            node_id=node_id,
            login_ok=False,
            host="",
            credential_reference=credential_reference,
            error="missing_host",
        )

    device_type = resolve_connection_device_type(
        network_driver=device.network_driver,
        platform=device.platform,
        override=network_driver_override,
    )

    try:
        # Disposable probe login — does not touch any pooled session, so a
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
        if not alive:
            failed = _device_failure(
                device,
                node_id=node_id,
                code="login_failed",
                message="SSH session opened but is not alive",
            )
            return "failure", _with_login_parsed(
                failed,
                node_id=node_id,
                login_ok=False,
                host=host,
                credential_reference=credential_reference,
                error="session_not_alive",
            )

        enriched = device.model_copy(update={"status": DeviceStatus.OK})
        return "success", _with_login_parsed(
            enriched,
            node_id=node_id,
            login_ok=True,
            host=host,
            credential_reference=credential_reference,
        )
    except Exception as exc:
        failed = _device_failure(
            device,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
        )
        return "failure", _with_login_parsed(
            failed,
            node_id=node_id,
            login_ok=False,
            host=host,
            credential_reference=credential_reference,
            error=str(exc),
        )


async def _try_login_logged(
    *,
    index: int,
    device_id: str,
    device: DeviceContext,
    total: int,
    run_id: Any,
    node_id: str,
    credential_reference: str,
    network_driver_override: str | None,
    username: str,
    password: str,
    netmiko: NetmikoService,
) -> tuple[str, DeviceContext]:
    host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
    logger.info(
        "login-successful device %d/%d id=%s host=%s: connecting run_id=%s",
        index,
        total,
        device_id,
        host,
        run_id,
    )
    outcome_name, updated = await _try_login(
        device_id=device_id,
        device=device,
        node_id=node_id,
        credential_reference=credential_reference,
        network_driver_override=network_driver_override,
        username=username,
        password=password,
        netmiko=netmiko,
    )
    logger.info(
        "login-successful device %d/%d id=%s host=%s: %s run_id=%s",
        index,
        total,
        device_id,
        host,
        outcome_name,
        run_id,
    )
    return outcome_name, updated


def _build_login_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    results: list[tuple[str, DeviceContext]],
    run_id: Any,
) -> list[StepOutcome]:
    buckets: dict[str, dict[str, DeviceContext]] = {"success": {}, "failure": {}}
    for device_id, (outcome_name, device) in zip(context.devices.keys(), results, strict=True):
        buckets[outcome_name][device_id] = device

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.login_counts": counts}

    logger.info(
        "login-successful finished success=%d failure=%d run_id=%s",
        counts["success"],
        counts["failure"],
        run_id,
    )

    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
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
        run.id,
        node_id,
        total,
        credential_reference,
        network_driver_override,
    )

    results = await asyncio.gather(
        *[
            _try_login_logged(
                index=index,
                device_id=device_id,
                device=device,
                total=total,
                run_id=run.id,
                node_id=node_id,
                credential_reference=credential_reference,
                network_driver_override=network_driver_override,
                username=username,
                password=password,
                netmiko=netmiko,
            )
            for index, (device_id, device) in enumerate(context.devices.items(), start=1)
        ]
    )
    return _build_login_outcomes(
        context=context,
        node_id=node_id,
        results=results,
        run_id=run.id,
    )
