"""Executor for the update-ise-tacacs-key step.

Sets ``tacacsSettings.sharedSecret`` on each device in Cisco ISE. The new key
comes from ``config["new_key"]`` — either a fixed value, or a
``{path.to.value}`` expression resolved per device against the device's
attribute bags (see ``workflow_steps.common.update_field_expression``), the
same convention ``update-nautobot-device`` uses for its field values.

Outcomes: a per-device miss (unresolved key expression, device not found in
ISE, or ISE rejected the update) marks that device ``DeviceStatus.FAILED``
but the step itself still emits ``"success"`` — a "proceed with survivors"
step, mirroring ``get-ise-tacacs-key``. The step emits ``"failure"`` instead
only when ISE itself couldn't be reached or authentication failed (a
pre-flight ``test_connection()`` check, and any bare ``ISEAPIError`` raised
mid-run) — a condition that affects every device equally.

Device resolution: when a device already came from ISE (``device.source ==
"ise"``, e.g. via Get from ISE), its ``device.id`` is the raw ISE NetworkDevice
id and is used directly. Otherwise the device is looked up by name via
``get_device_by_name`` — a single lookup, not the multi-tier fallback chain
``get-ise-tacacs-key`` uses for reads, since picking the wrong device to write
to is worse than failing closed.

ISE's ERS ``PUT`` replaces the whole ``tacacsSettings`` sub-object if it's
present in the payload at all (``ISENetworkDeviceService.update_device``'s own
merge is only one level deep), so the current ``tacacsSettings`` is fetched
first and only ``sharedSecret`` is overridden before the update call — this
preserves sibling settings such as ``enableKeyWrap``/``connectModeOptions``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError
from services.ise.network_device_service import ISENetworkDeviceService
from services.ise.source_config_service import ISESourceNotFoundError
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.update_field_expression import resolve_update_field_expression

logger = logging.getLogger(__name__)

_STEP_ID = "update-ise-tacacs-key"


def _mark_failed(device: DeviceContext, *, node_id: str, code: str, message: str) -> DeviceContext:
    error = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error]}
    )


async def _resolve_ise_device_id(
    device: DeviceContext, device_service: ISENetworkDeviceService
) -> str | None:
    if device.source == "ise" and device.id:
        return device.id
    try:
        result = await device_service.get_device_by_name(device.name)
    except ISENotFoundError:
        return None
    detail = result.get("NetworkDevice") or {}
    device_id = detail.get("id")
    return str(device_id) if device_id else None


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    source_id = (config.get("ise_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: ise_source_id is not configured")

    raw_new_key = (config.get("new_key") or "").strip()
    if not raw_new_key:
        raise ValueError(f"{_STEP_ID}: new_key is not configured")

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    source_config_service = service_factory.build_ise_source_config_service(db)
    try:
        credentials = source_config_service.resolve_credentials(source_id)
    except ISESourceNotFoundError as exc:
        raise ValueError(f"{_STEP_ID}: ISE source '{source_id}' not found") from exc
    except ISEValidationError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    device_service = service_factory.build_ise_network_device_service(credentials)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    try:
        await device_service.test_connection()
    except ISEAPIError as exc:
        logger.warning("%s: could not reach ISE source '%s': %s", _STEP_ID, source_id, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not reach ISE source '{source_id}': {exc}",
            )
        ]

    updated_devices: dict[str, DeviceContext] = {}
    updated_count = 0
    failed_count = 0

    for device_id, device in context.devices.items():
        new_key_value = resolve_update_field_expression(
            device=device,
            field_key="new_key",
            raw_value=raw_new_key,
            run_id=context.run_id,
        )
        if not new_key_value:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="tacacs_key_unresolved",
                message=f"new_key expression did not resolve to a value for '{device.name}'",
            )
            failed_count += 1
            continue

        try:
            ise_device_id = await _resolve_ise_device_id(device, device_service)
        except ISEAPIError as exc:
            logger.warning(
                "%s: lost connection to ISE source '%s' while resolving device '%s': %s",
                _STEP_ID,
                source_id,
                device.name,
                exc,
            )
            return [
                StepOutcome(
                    name="failure",
                    context=context,
                    summary=f"lost connection to ISE source '{source_id}': {exc}",
                )
            ]

        if not ise_device_id:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="ise_device_not_found",
                message=f"could not locate device '{device.name}' in ISE source '{source_id}'",
            )
            failed_count += 1
            continue

        try:
            current = await device_service.get_device(ise_device_id)
            current_tacacs = current.get("NetworkDevice", {}).get("tacacsSettings") or {}
            merged_tacacs = {**current_tacacs, "sharedSecret": new_key_value}
            await device_service.update_device(ise_device_id, {"tacacsSettings": merged_tacacs})
        except (ISENotFoundError, ISEValidationError) as exc:
            updated_devices[device_id] = _mark_failed(
                device,
                node_id=node_id,
                code="tacacs_key_update_rejected",
                message=f"ISE rejected the TACACS+ key update for '{device.name}': {exc}",
            )
            failed_count += 1
            continue
        except ISEAPIError as exc:
            logger.warning(
                "%s: lost connection to ISE source '%s' while updating device '%s': %s",
                _STEP_ID,
                source_id,
                device.name,
                exc,
            )
            return [
                StepOutcome(
                    name="failure",
                    context=context,
                    summary=f"lost connection to ISE source '{source_id}': {exc}",
                )
            ]

        updated_devices[device_id] = set_device_attribute(
            device, "tacacs.shared_secret", seal_secret(new_key_value)
        )
        updated_count += 1
        logger.info("%s: updated tacacs key for device=%s", _STEP_ID, device.name)

    metadata = {
        **context.metadata,
        f"{node_id}.total": len(context.devices),
        f"{node_id}.updated_count": updated_count,
        f"{node_id}.failed_count": failed_count,
    }

    logger.info(
        "%s finished node_id=%s updated=%d failed=%d run_id=%s",
        _STEP_ID,
        node_id,
        updated_count,
        failed_count,
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": updated_devices, "metadata": metadata}),
            summary=f"updated {updated_count}, failed {failed_count}",
        )
    ]
