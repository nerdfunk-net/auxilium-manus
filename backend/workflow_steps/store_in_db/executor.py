"""Executor for the store-in-db step.

Rows are keyed by (device_name, storage_key), so fan-out children and
independent sibling branches within one run never collide (each processes a
disjoint device set). A same-device/same-key race across concurrent runs is
resolved by DeviceDataRecordRepository.upsert's IntegrityError retry — no
Fan-In node is required here, unlike store-artifact's git/filesystem sinks.
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
from services.workflow_context.attribute_path import resolve_device_value
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret
from workflow_steps.common.content_resolver import list_exportable_content

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_CONTENT_SOURCES = frozenset(
    {"device_data", "attribute_bags", "single_attribute", "rendered_template"}
)


def _parse_storage_key(config: dict[str, Any]) -> str:
    storage_key = str(config.get("storage_key") or "").strip()
    if not storage_key:
        raise ValueError("store-in-db: storage_key is required")
    return storage_key


def _parse_content_source(config: dict[str, Any]) -> str:
    content_source = str(config.get("content_source") or "").strip().lower()
    if content_source not in _CONTENT_SOURCES:
        raise ValueError(
            f"store-in-db: content_source must be one of {sorted(_CONTENT_SOURCES)}"
        )
    return content_source


def _parse_bool(config: dict[str, Any], key: str, *, default: bool = False) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


async def _resolve_rendered_template(
    device: DeviceContext,
    *,
    config: dict[str, Any],
    artifact_service: ArtifactService,
) -> Any:
    source_step_node_id = str(config.get("source_step_node_id") or "").strip()
    if not source_step_node_id:
        raise ValueError(
            "store-in-db: source_step_node_id is required when content_source=rendered_template"
        )
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None

    items = list_exportable_content(
        device,
        content_source="rendered_template",
        source_step_node_id=source_step_node_id,
        parsed_output_key=parsed_output_key,
    )
    if not items:
        return None

    rendered: dict[str, str] = {}
    for item in items:
        content = await artifact_service.resolve(item.artifact_ref)
        rendered[str(item.extra.get("output_key") or item.kind)] = content

    if parsed_output_key and len(rendered) == 1:
        return next(iter(rendered.values()))
    return rendered


async def _resolve_device_data(
    device: DeviceContext,
    *,
    content_source: str,
    config: dict[str, Any],
    artifact_service: ArtifactService,
) -> Any:
    if content_source == "device_data":
        return {"attribute_bags": device.attribute_bags, "parsed": device.parsed}

    if content_source == "attribute_bags":
        return dict(device.attribute_bags)

    if content_source == "single_attribute":
        attribute_path = str(config.get("attribute_path") or "").strip()
        if not attribute_path:
            raise ValueError(
                "store-in-db: attribute_path is required when content_source=single_attribute"
            )
        value = resolve_device_value(device, attribute_path)
        if is_sealed_secret(value):
            if not _parse_bool(config, "allow_secret_storage"):
                raise ValueError(
                    f"store-in-db: attribute_path {attribute_path!r} resolves to a "
                    "secret-valued attribute, which cannot be stored in the database "
                    "unless allow_secret_storage is enabled"
                )
            # Operator explicitly accepted the risk (allow_secret_storage) — decrypt
            # and store the cleartext value, per doc/WORKFLOW-STEPS.md's "Secret-valued
            # attributes": this is only ever an explicit, documented operator choice.
            return unwrap_secret(value)
        return value

    if content_source == "rendered_template":
        return await _resolve_rendered_template(
            device, config=config, artifact_service=artifact_service
        )

    raise ValueError(f"store-in-db: unsupported content_source {content_source!r}")


def _device_failure(*, device: DeviceContext, node_id: str, exc: Exception) -> DeviceContext:
    err = DeviceError(
        node_id=node_id,
        step_id="store-in-db",
        code=type(exc).__name__.lower(),
        message=str(exc),
    )
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
    del device_sessions

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    storage_key = _parse_storage_key(config)
    content_source = _parse_content_source(config)

    logger.info(
        "store-in-db started run_id=%s node_id=%s devices=%d storage_key=%s content_source=%s",
        run.id,
        node_id,
        len(context.devices),
        storage_key,
        content_source,
    )

    db = get_db_session()
    try:
        service = DeviceDataService(db)
        success_devices: dict[str, DeviceContext] = {}
        failed_devices: dict[str, DeviceContext] = {}
        for device_id, device in context.devices.items():
            try:
                data = await _resolve_device_data(
                    device,
                    content_source=content_source,
                    config=config,
                    artifact_service=artifact_service,
                )
                if data is None:
                    raise ValueError(
                        f"No {content_source!r} content available for device {device.name}. "
                        "Ensure an upstream step produced the selected data."
                    )
                service.store_device_data(
                    device_name=device.name, storage_key=storage_key, data=data
                )
                success_devices[device_id] = device.model_copy(update={"status": DeviceStatus.OK})
            except Exception as exc:
                failed_devices[device_id] = _device_failure(device=device, node_id=node_id, exc=exc)
    finally:
        db.close()

    logger.info(
        "store-in-db finished success=%d failure=%d run_id=%s",
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
