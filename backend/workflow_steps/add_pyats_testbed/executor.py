"""Executor for the add-pyats-testbed step.

Pure local computation -- no network I/O. Resolves the configured credential
once, computes each device's pyATS os/host, and writes a sealed connection
bundle into every device's ``attribute_bags["pyats_testbed"]`` bag so
downstream pyATS-backed steps (e.g. get-pyats-config) don't need their own
credential/source configuration. See "Calling pyATS from a step" in
doc/WORKFLOW-STEPS.md.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.pyats.platform import resolve_pyats_os
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.add_pyats_testbed.config import get_config
from workflow_steps.common.credential_resolver import resolve_generic_credential

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "add-pyats-testbed"


def _parse_config(config: dict[str, Any]) -> tuple[str, str, str | None]:
    defaults = get_config()
    pyats_source_id = str(config.get("pyats_source_id") or defaults["pyats_source_id"]).strip()
    if not pyats_source_id:
        raise ValueError(f"{_STEP_ID}: pyats_source_id is required")

    credential_reference = str(
        config.get("credential_reference") or defaults["credential_reference"]
    ).strip()
    if not credential_reference:
        raise ValueError(f"{_STEP_ID}: credential_reference is required")

    network_driver_override = str(config.get("network_driver_override") or "").strip() or None
    return pyats_source_id, credential_reference, network_driver_override


def _build_testbed_device(
    device: DeviceContext,
    *,
    pyats_source_id: str,
    username: str,
    sealed_password: dict[str, Any],
    network_driver_override: str | None,
) -> DeviceContext:
    host = bare_hostname(device.primary_ip4, device.hostname)
    os_name = resolve_pyats_os(
        network_driver=device.network_driver,
        platform=device.platform,
        override=network_driver_override,
    )
    bag = {
        "pyats_source_id": pyats_source_id,
        "host": host,
        "os": os_name,
        "username": username,
        "password": sealed_password,
    }
    return device.model_copy(
        update={
            "attribute_bags": {**device.attribute_bags, "pyats_testbed": bag},
            "capabilities": device.capabilities | {Capability.PYATS_TESTBED},
        }
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
    del artifact_service, device_sessions  # unused: no artifacts, no SSH sessions

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    pyats_source_id, credential_reference, network_driver_override = _parse_config(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d pyats_source_id=%s",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        pyats_source_id,
    )

    username, password = resolve_generic_credential(
        db, credential_reference, acting_user_id=run.triggered_by_id
    )
    sealed_password = seal_secret(password)

    devices = {
        device_id: _build_testbed_device(
            device,
            pyats_source_id=pyats_source_id,
            username=username,
            sealed_password=sealed_password,
            network_driver_override=network_driver_override,
        )
        for device_id, device in context.devices.items()
    }

    logger.info(
        "%s finished run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        run.id,
        node_id,
        len(devices),
    )

    return [StepOutcome(name="success", context=context.model_copy(update={"devices": devices}))]
