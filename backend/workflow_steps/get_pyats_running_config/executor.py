"""Executor for the get-pyats-running-config step.

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

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.failure_records import INVALID_RESPONSE
from workflow_steps.common.jinja_render import parse_output_key
from workflow_steps.common.pyats_batch import (
    resolve_source_credentials,
    run_batched,
    shim_device_failure,
    validate_and_group_devices,
)
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_session import require_session
from workflow_steps.get_pyats_running_config.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-pyats-running-config"
_RUNNING_COMMAND = "show running-config"
_COMMANDS = [_RUNNING_COMMAND]


def _shape_result(
    *,
    device_id: str,
    device: DeviceContext,
    output_key: str,
    result: dict[str, Any] | None,
) -> DeviceContext | Fail:
    if not result or not result.get("success", False):
        message, failure = shim_device_failure(result)
        logger.warning(
            "%s device connect/parse failed device=%s error=%s", _STEP_ID, device_id, message
        )
        return Fail("device_error", message, failure)

    commands = result.get("commands") or {}
    running_entry = commands.get(_RUNNING_COMMAND)
    if not running_entry:
        return Fail(
            "parse_failed", f"{_RUNNING_COMMAND}: the shim returned no result for this command",
            failure=INVALID_RESPONSE,
        )
    if running_entry.get("error"):
        return Fail(
            "parse_failed",
            f"{_RUNNING_COMMAND}: {running_entry['error']}",
            failure=INVALID_RESPONSE,
        )
    if running_entry.get("parsed") is None:
        return Fail(
            "parse_failed",
            f"{_RUNNING_COMMAND}: the shim returned no parsed data",
            failure=INVALID_RESPONSE,
        )

    entry = {"running": running_entry.get("parsed")}
    parsed = dict(device.parsed)
    parsed[output_key] = entry
    return device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
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

    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, _STEP_ID)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d output_key=%s",
        _STEP_ID,
        log_run_id(run),
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

    grouped = {device_id for device_group in groups.values() for device_id, _ in device_group}

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return _shape_result(
            device_id=device_id,
            device=device,
            output_key=output_key,
            result=raw_results.get(device_id),
        )

    batch = await run_per_device(context, work, node_id=node_id, step_id=_STEP_ID, only=grouped)
    success_devices = batch.ok
    failed_devices.update(batch.failed)

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
        log_run_id(run),
    )

    return build_outcomes(context, success_devices, failed_devices)
