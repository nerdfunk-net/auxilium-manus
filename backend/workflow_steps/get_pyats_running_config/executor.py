"""Executor for the get-pyats-config step.

Fetches running-config via the pyATS shim's ``POST /v1/jobs``
(``operation: "parse"``) and stores Genie's structured result into
``device.parsed``. Never imports pyats/genie directly -- see "Calling pyATS
from a step" in doc/WORKFLOW-STEPS.md. Device connection info and
credentials come entirely from the ``pyats_testbed`` bag written by an
upstream add-pyats-testbed step; this step resolves no credentials of its
own.

Startup-config is intentionally out of scope: genieparser has no registered
parser for ``show startup-config`` on any platform (confirmed against the
CiscoTestAutomation/genieparser source -- there is no ``cli_command = 'show
startup-config'`` anywhere in it, only dozens for ``show running-config``),
so requesting it via ``operation="parse"`` would fail on every device, every
time. Raw (unparsed) config capture -- running or startup -- is already
``get-device-configs``'s job (Netmiko-based); this step is Genie-structured
parsing only.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.jinja_render import parse_output_key
from workflow_steps.common.pyats_batch import (
    resolve_source_credentials,
    run_batched,
    validate_and_group_devices,
)
from workflow_steps.get_pyats_config.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-pyats-config"
_RUNNING_COMMAND = "show running-config"
_COMMANDS = [_RUNNING_COMMAND]


def _fail_device(
    *, device: DeviceContext, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def _shape_result(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    output_key: str,
    result: dict[str, Any] | None,
) -> tuple[str, DeviceContext, bool]:
    if not result or not result.get("success", False):
        message = (result or {}).get("error") or "pyATS shim reported failure for this device"
        logger.warning(
            "%s device connect/parse failed device=%s error=%s", _STEP_ID, device_id, message
        )
        failed = _fail_device(device=device, node_id=node_id, code="device_error", message=message)
        return device_id, failed, False

    commands = result.get("commands") or {}
    running_entry = commands.get(_RUNNING_COMMAND) or {}
    if running_entry.get("error"):
        failed = _fail_device(
            device=device,
            node_id=node_id,
            code="parse_failed",
            message=f"{_RUNNING_COMMAND}: {running_entry['error']}",
        )
        return device_id, failed, False

    entry = {"running": running_entry.get("parsed")}
    parsed = dict(device.parsed)
    parsed[output_key] = entry
    enriched = device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
        }
    )
    return device_id, enriched, True


def _partition(
    results: list[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        (success if ok else failed)[device_id] = updated_device
    return success, failed


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

    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d output_key=%s",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        output_key,
    )

    source_ids = {
        str(device.attribute_bags["pyats_testbed"]["pyats_source_id"])
        for device in context.devices.values()
        if isinstance(device.attribute_bags.get("pyats_testbed"), dict)
        and device.attribute_bags["pyats_testbed"].get("pyats_source_id")
    }
    source_credentials, source_errors = resolve_source_credentials(db, source_ids)
    groups, failed_devices = validate_and_group_devices(
        devices=context.devices,
        node_id=node_id,
        step_id=_STEP_ID,
        source_credentials=source_credentials,
        source_errors=source_errors,
    )

    raw_results: dict[str, dict[str, Any]] = {}
    if groups:
        shim = service_factory.get_pyats_app_service()
        group_results = await asyncio.gather(
            *[
                run_batched(
                    shim=shim,
                    credentials=source_credentials[source_id],
                    operation="parse",
                    commands=_COMMANDS,
                    device_group=device_group,
                )
                for source_id, device_group in groups.items()
            ]
        )
        for group_result in group_results:
            raw_results.update(group_result)

    shaped = [
        _shape_result(
            device_id=device_id,
            device=context.devices[device_id],
            node_id=node_id,
            output_key=output_key,
            result=raw_results.get(device_id),
        )
        for source_id, device_group in groups.items()
        for device_id, _shim_device in device_group
    ]
    success_devices, newly_failed = _partition(shaped)
    failed_devices.update(newly_failed)

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        run.id,
    )

    outcomes = [
        StepOutcome(name="success", context=context.model_copy(update={"devices": success_devices}))
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure", context=context.model_copy(update={"devices": failed_devices})
            )
        )
    return outcomes
