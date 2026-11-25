"""Executor for the get-pyats-snapshot step.

Captures a Genie "learn" snapshot -- structured *operational* device state
(BGP, OSPF, interfaces, platform, ...) as opposed to configuration text --
via the pyATS shim's ``POST /v1/jobs`` (``operation: "learn"``). Never
imports pyats/genie directly -- see "Calling pyATS from a step" in
doc/WORKFLOW-STEPS.md. Device connection info and credentials come entirely
from the ``pyats_testbed`` bag written by an upstream add-pyats-testbed
step; this step resolves no credentials of its own.

Unlike get-pyats-running-config (which requires both requested commands to succeed),
feature support varies a lot by platform -- VRF/ISIS/NAT are often simply
not configured or not supported on a given device, so a per-feature learn
failure is the *normal* case, not exceptional (the same lesson learned with
get-pyats-running-config's ``show startup-config`` ParserNotFound issue). A device
only fails here if the shim call/connect itself fails, or if literally every
requested feature failed to learn; partial coverage is a normal success with
per-feature success/error recorded inside the stored snapshot.

The full per-feature Genie Ops data is stored via ``artifact_service`` (same
durable, run-scoped storage ``get-device-configs`` already uses for raw
config content); a lightweight per-feature success/error summary plus the
resulting ``ArtifactRef`` is written into ``device.parsed[node_id][output_key]`` for
downstream Jinja/Log Attributes steps and the run-detail UI.
"""

from __future__ import annotations

import asyncio
import json
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
from services.workflow_context.node_result import set_node_result
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.failure_records import INVALID_RESPONSE
from workflow_steps.common.pyats_batch import (
    resolve_source_credentials,
    run_batched,
    shim_device_failure,
    validate_and_group_devices,
)
from workflow_steps.common.pyats_features import parse_feature_list
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_output_key
from workflow_steps.get_pyats_snapshot.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-pyats-snapshot"
_SNAPSHOT_KIND = "pyats_snapshot"


def _parse_features(config: dict[str, Any]) -> list[str]:
    return parse_feature_list(config.get("features"), step_id=_STEP_ID)


async def _shape_and_store_result(
    *,
    device_id: str,
    device: DeviceContext,
    output_key: str,
    features: list[str],
    run_id: str,
    node_id: str,
    artifact_service: ArtifactService,
    result: dict[str, Any] | None,
) -> DeviceContext | Fail:
    if not result or not result.get("success", False):
        message, failure = shim_device_failure(result)
        logger.warning(
            "%s device connect/learn failed device=%s error=%s", _STEP_ID, device_id, message
        )
        return Fail("device_error", message, failure)

    commands = result.get("commands") or {}
    feature_results: dict[str, dict[str, Any]] = {}
    for feature in features:
        entry = commands.get(feature)
        if not entry:
            # No entry at all is a failure, not an empty success.
            feature_results[feature] = {
                "success": False,
                "error": "the shim returned no result for this feature",
            }
        elif entry.get("error"):
            feature_results[feature] = {"success": False, "error": entry["error"]}
        elif entry.get("parsed") is None:
            feature_results[feature] = {
                "success": False,
                "error": "the shim returned no parsed data for this feature",
            }
        else:
            feature_results[feature] = {"success": True, "data": entry.get("parsed")}

    if all(not r["success"] for r in feature_results.values()):
        message = "; ".join(f"{name}: {r['error']}" for name, r in feature_results.items())
        logger.warning(
            "%s every feature failed device=%s error=%s", _STEP_ID, device_id, message
        )
        return Fail("snapshot_failed", message, failure=INVALID_RESPONSE)

    content = json.dumps(feature_results, indent=2, default=str)
    artifact_ref = await artifact_service.store(
        content=content,
        kind=_SNAPSHOT_KIND,
        device_id=device_id,
        run_id=run_id,
        media_type="application/json",
    )

    entry = {
        "kind": _SNAPSHOT_KIND,
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "step_node_id": node_id,
        "features": {
            name: {"success": r["success"], "error": r.get("error")}
            for name, r in feature_results.items()
        },
    }
    parsed = set_node_result(device.parsed, node_id, output_key, entry)
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
    del device_sessions  # unused: pyATS connects via the shim, not Netmiko

    features = _parse_features(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])

    db = require_session(run, _STEP_ID)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d features=%s output_key=%s",
        _STEP_ID,
        log_run_id(run),
        node_id,
        len(context.devices),
        features,
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
                    operation="learn",
                    commands=features,
                    device_group=device_group,
                )
                for source_id, device_group in groups.items()
            ]
        )
        for group_result in group_results:
            raw_results.update(group_result)

    grouped = {device_id for device_group in groups.values() for device_id, _ in device_group}

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _shape_and_store_result(
            device_id=device_id,
            device=device,
            output_key=output_key,
            features=features,
            run_id=context.run_id,
            node_id=node_id,
            artifact_service=artifact_service,
            result=raw_results.get(device_id),
        )

    # The artifact store is inside the per-device boundary: one failing store fails that device
    # and keeps the shim results of the others (W7-03).
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
