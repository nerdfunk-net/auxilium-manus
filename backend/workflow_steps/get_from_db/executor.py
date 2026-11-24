"""Executor for the get-from-db step.

Counterpart of store-in-db: reads the record stored for each device under
``storage_key`` (table ``device_data_records``, keyed by device name) and writes
its data into the device attribute at ``destination_path``. A device without a
record is marked failed and routed to the ``failure`` outcome.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.device_data.device_data_service import DeviceDataService
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.common.run_logging import log_run_id

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-from-db"


def _parse_required(config: dict[str, Any], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise ValueError(f"{_STEP_ID}: {key} is required")
    return value


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
        log_run_id(run),
        node_id,
        len(context.devices),
        storage_key,
    )

    db = get_db_session()
    try:
        service = DeviceDataService(db)

        async def read_device(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
            rendered_key = render_placeholder_template(storage_key, device)
            # A blocking database query: keep it off the event loop.
            record = await asyncio.to_thread(
                service.get_device_data, device_name=device.name, storage_key=rendered_key
            )
            if record is None:
                return Fail(
                    "record_not_found",
                    f"No stored data for device {device.name!r} under storage_key {rendered_key!r}",
                    FailureInfo(phase="internal", kind="not_found"),
                )
            updated = set_device_attribute(device, destination_path, record.data)
            return updated.model_copy(update={"status": DeviceStatus.OK})

        # One session, one device after the other (concurrency=1).
        batch = await run_per_device(
            context, read_device, node_id=node_id, step_id=_STEP_ID, concurrency=1
        )
    finally:
        db.close()
    success_devices, failed_devices = batch.ok, batch.failed

    logger.info(
        "get-from-db finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        log_run_id(run),
    )

    return build_outcomes(context, success_devices, failed_devices)
