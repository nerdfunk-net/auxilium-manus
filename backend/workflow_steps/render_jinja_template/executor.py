"""Executor for the render-jinja-template step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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
from workflow_steps.common.jinja_render import (
    JinjaTemplateError,
    build_jinja_context,
    parse_output_key,
    render_jinja_template,
    validate_jinja_template,
)
from workflow_steps.render_jinja_template.config import get_config

logger = logging.getLogger(__name__)


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_template(config: dict[str, Any]) -> str:
    template = str(config.get("template") or _default_config()["template"]).strip()
    if not template:
        raise ValueError("render-jinja-template: template is required")
    validate_jinja_template(template)
    return template


def _parsed_template_entry(
    *,
    artifact_ref: Any,
    node_id: str,
    output_key: str,
    size_bytes: int,
) -> dict[str, Any]:
    return {
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "step_node_id": node_id,
        "output_key": output_key,
        "size_bytes": size_bytes,
        "kind": "rendered_template",
    }


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

    output_key = parse_output_key(config.get("output_key") or _default_config()["output_key"])
    template = _parse_template(config)

    logger.info(
        "render-jinja-template run_id=%s devices=%d output_key=%s",
        run.id,
        len(context.devices),
        output_key,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def render_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            jinja_context = build_jinja_context(
                device,
                run_id=context.run_id,
                workflow_id=context.workflow_id,
            )
            rendered = render_jinja_template(template, jinja_context)
            artifact_ref = await artifact_service.store(
                content=rendered,
                kind="rendered_template",
                device_id=device_id,
                run_id=context.run_id,
            )
            parsed = dict(device.parsed)
            parsed[output_key] = _parsed_template_entry(
                artifact_ref=artifact_ref,
                node_id=node_id,
                output_key=output_key,
                size_bytes=len(rendered.encode("utf-8")),
            )
            enriched = device.model_copy(
                update={
                    "parsed": parsed,
                    "capabilities": device.capabilities | {Capability.PARSED},
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, True
        except (JinjaTemplateError, ValueError) as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="render-jinja-template",
                code="template_error",
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id="render-jinja-template",
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False

    results = await asyncio.gather(
        *[render_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    metadata = {
        **context.metadata,
        f"{node_id}.rendered_template_key": output_key,
        f"{node_id}.rendered_success_count": len(success_devices),
        f"{node_id}.rendered_failure_count": len(failed_devices),
    }

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices, "metadata": metadata}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices, "metadata": metadata}),
            )
        )
    return outcomes
