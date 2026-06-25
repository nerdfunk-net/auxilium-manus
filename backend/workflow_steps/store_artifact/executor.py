"""Executor for the store-artifact step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.config import settings
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.artifacts.sinks import ArtifactSink, FilesystemArtifactSink, StoredExport
from workflow_steps.common.content_resolver import (
    ExportableContent,
    list_exportable_content,
    parse_content_source,
)
from workflow_steps.common.device_template import (
    TemplateRenderOptions,
    parse_strict_templates,
    render_device_template,
)

logger = logging.getLogger(__name__)

_DESTINATIONS = frozenset({"filesystem"})


def _default_config() -> dict[str, Any]:
    from workflow_steps.store_artifact.config import get_config

    return get_config()


def _build_sink(config: dict[str, Any]) -> ArtifactSink:
    destination = str(config.get("destination") or "filesystem").strip().lower()
    if destination not in _DESTINATIONS:
        raise ValueError(
            f"store-artifact: destination must be one of {sorted(_DESTINATIONS)}"
        )
    if destination == "filesystem":
        output_subdirectory = str(
            config.get("output_subdirectory")
            or _default_config().get("output_subdirectory")
            or "exports"
        ).strip()
        return FilesystemArtifactSink(
            settings.data_directory,
            output_subdirectory=output_subdirectory,
        )
    raise ValueError(f"store-artifact: unsupported destination {destination!r}")


def _filename_template(config: dict[str, Any], item: ExportableContent) -> str:
    del item
    return str(
        config.get("filename_template")
        or _default_config().get("filename_template")
        or "{device.name}_{run.timestamp}.cfg"
    ).strip()


def _relative_export_path(
    *,
    device: DeviceContext,
    item: ExportableContent,
    config: dict[str, Any],
    index: int,
    run_id: str,
) -> str:
    template = _filename_template(config, item)
    extra = dict(item.extra)
    extra["index"] = index + 1
    return render_device_template(
        template,
        device,
        extra=extra,
        options=TemplateRenderOptions(
            strict=parse_strict_templates(config),
            run_id=run_id,
        ),
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    content_source = parse_content_source(config)
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    sink = _build_sink(config)

    logger.info(
        "store-artifact run_id=%s devices=%d source=%s destination=%s",
        run.id,
        len(context.devices),
        content_source,
        sink.destination,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    metadata = dict(context.metadata)

    async def store_for_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool, list[dict[str, Any]]]:
        export_items = list_exportable_content(
            device,
            content_source=content_source,
            source_step_node_id=source_step_node_id,
        )
        if not export_items:
            err = DeviceError(
                node_id=node_id,
                step_id="store-artifact",
                code="missing_content",
                message=(
                    f"No {content_source!r} content available for device {device_id}. "
                    "Ensure an upstream step produced the selected data."
                ),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False, []

        stored_records: list[dict[str, Any]] = []
        try:
            for index, item in enumerate(export_items):
                content = await artifact_service.resolve(item.artifact_ref)
                relative_path = _relative_export_path(
                    device=device,
                    item=item,
                    config=config,
                    index=index,
                    run_id=context.run_id,
                )
                export: StoredExport = await sink.write_text(
                    relative_path=relative_path,
                    content=content,
                    workflow_id=context.workflow_id,
                    run_id=context.run_id,
                )
                stored_records.append(
                    {
                        "device_id": device_id,
                        "content_source": content_source,
                        "kind": item.kind,
                        "path": export.path,
                        "destination": export.destination,
                        "size_bytes": export.size_bytes,
                        "sha256": export.sha256,
                        **item.extra,
                    }
                )

            enriched = device.model_copy(update={"status": DeviceStatus.OK})
            return device_id, enriched, True, stored_records
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="store-artifact",
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False, stored_records

    results = await asyncio.gather(
        *[store_for_device(device_id, device) for device_id, device in context.devices.items()]
    )

    all_stored: list[dict[str, Any]] = []
    for device_id, updated_device, ok, stored_records in results:
        all_stored.extend(stored_records)
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    if all_stored:
        metadata_key = f"{node_id}.stored_artifacts"
        metadata[metadata_key] = all_stored

    logger.info(
        "store-artifact wrote %d file(s) for %d/%d devices run_id=%s",
        len(all_stored),
        len(success_devices),
        len(context.devices),
        run.id,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(
                update={"devices": success_devices, "metadata": metadata}
            ),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
            )
        )
    return outcomes
