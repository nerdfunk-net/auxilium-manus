"""Executor for the get-pyats-snapshot step.

Captures a Genie "learn" snapshot -- structured *operational* device state
(BGP, OSPF, interfaces, platform, ...) as opposed to configuration text --
via the pyATS shim's ``POST /v1/jobs`` (``operation: "learn"``). Never
imports pyats/genie directly -- see "Calling pyATS from a step" in
doc/WORKFLOW-STEPS.md. Device connection info and credentials come entirely
from the ``pyats_testbed`` bag written by an upstream add-pyats-testbed
step; this step resolves no credentials of its own.

Unlike get-pyats-config (which requires both requested commands to succeed),
feature support varies a lot by platform -- VRF/ISIS/NAT are often simply
not configured or not supported on a given device, so a per-feature learn
failure is the *normal* case, not exceptional (the same lesson learned with
get-pyats-config's ``show startup-config`` ParserNotFound issue). A device
only fails here if the shim call/connect itself fails, or if literally every
requested feature failed to learn; partial coverage is a normal success with
per-feature success/error recorded inside the stored snapshot.

The full per-feature Genie Ops data is stored via ``artifact_service`` (same
durable, run-scoped storage ``get-device-configs`` already uses for raw
config content); a lightweight per-feature success/error summary plus the
resulting ``ArtifactRef`` is written into ``device.parsed[output_key]`` for
downstream Jinja/Log Attributes steps and the run-detail UI.
"""

from __future__ import annotations

import asyncio
import json
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
from workflow_steps.get_pyats_snapshot.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-pyats-snapshot"
_SNAPSHOT_KIND = "pyats_snapshot"


def _parse_features(config: dict[str, Any]) -> list[str]:
    raw = config.get("features")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{_STEP_ID}: features must be a non-empty list of Genie feature names")
    features: list[str] = []
    seen: set[str] = set()
    for item in raw:
        name = str(item).strip()
        if not name:
            raise ValueError(f"{_STEP_ID}: features entries must be non-empty strings")
        if name not in seen:
            seen.add(name)
            features.append(name)
    return features


def _fail_device(
    *, device: DeviceContext, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


async def _shape_and_store_result(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    output_key: str,
    features: list[str],
    run_id: str,
    artifact_service: ArtifactService,
    result: dict[str, Any] | None,
) -> tuple[str, DeviceContext, bool]:
    if not result or not result.get("success", False):
        message = (result or {}).get("error") or "pyATS shim reported failure for this device"
        logger.warning(
            "%s device connect/learn failed device=%s error=%s", _STEP_ID, device_id, message
        )
        failed = _fail_device(device=device, node_id=node_id, code="device_error", message=message)
        return device_id, failed, False

    commands = result.get("commands") or {}
    feature_results: dict[str, dict[str, Any]] = {}
    for feature in features:
        entry = commands.get(feature) or {}
        if entry.get("error"):
            feature_results[feature] = {"success": False, "error": entry["error"]}
        else:
            feature_results[feature] = {"success": True, "data": entry.get("parsed")}

    if all(not r["success"] for r in feature_results.values()):
        message = "; ".join(f"{name}: {r['error']}" for name, r in feature_results.items())
        logger.warning(
            "%s every feature failed device=%s error=%s", _STEP_ID, device_id, message
        )
        failed = _fail_device(
            device=device, node_id=node_id, code="snapshot_failed", message=message
        )
        return device_id, failed, False

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
    del device_sessions  # unused: pyATS connects via the shim, not Netmiko

    features = _parse_features(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    output_key = parse_output_key(config.get("output_key") or get_config()["output_key"])

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d features=%s output_key=%s",
        _STEP_ID,
        run.id,
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

    shaped = await asyncio.gather(
        *[
            _shape_and_store_result(
                device_id=device_id,
                device=context.devices[device_id],
                node_id=node_id,
                output_key=output_key,
                features=features,
                run_id=context.run_id,
                artifact_service=artifact_service,
                result=raw_results.get(device_id),
            )
            for source_id, device_group in groups.items()
            for device_id, _shim_device in device_group
        ]
    )
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
