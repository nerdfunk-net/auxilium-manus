"""Executor for the get-from-db step.

Counterpart of store-in-db: reads the record stored for each device under
``storage_key`` (table ``device_data_records``, keyed by device name) and writes
its data into the device attribute at ``destination_path``. A device without a
record is marked failed and routed to the ``failure`` outcome.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.device_data.device_data_service import DeviceDataService
from workflow_steps.common.attribute_write import set_device_attribute

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-from-db"


def _parse_required(config: dict[str, Any], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise ValueError(f"{_STEP_ID}: {key} is required")
    return value


def _device_failure(
    *, device: DeviceContext, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [*device.errors, err],
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
    del artifact_service, device_sessions

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    storage_key = _parse_required(config, "storage_key")
    destination_path = _parse_required(config, "destination_path")

    logger.info(
        "get-from-db started run_id=%s node_id=%s devices=%d storage_key=%s",
        run.id,
        node_id,
        len(context.devices),
        storage_key,
    )

    db = get_db_session()
    try:
        service = DeviceDataService(db)
        success_devices: dict[str, DeviceContext] = {}
        failed_devices: dict[str, DeviceContext] = {}
        for device_id, device in context.devices.items():
            try:
                record = service.get_device_data(device_name=device.name, storage_key=storage_key)
                if record is None:
                    failed_devices[device_id] = _device_failure(
                        device=device,
                        node_id=node_id,
                        code="record_not_found",
                        message=(
                            f"No stored data for device {device.name!r} "
                            f"under storage_key {storage_key!r}"
                        ),
                    )
                    continue
                updated = set_device_attribute(device, destination_path, record.data)
                success_devices[device_id] = updated.model_copy(update={"status": DeviceStatus.OK})
            except Exception as exc:
                failed_devices[device_id] = _device_failure(
                    device=device,
                    node_id=node_id,
                    code=type(exc).__name__.lower(),
                    message=str(exc),
                )
    finally:
        db.close()

    logger.info(
        "get-from-db finished success=%d failure=%d run_id=%s",
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
