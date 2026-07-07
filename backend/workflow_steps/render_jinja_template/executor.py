"""Executor for the render-jinja-template step."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    CommandResult,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.templates.exceptions import TemplateNotFoundError
from services.templates.templates_service import TemplatesService
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


def _load_stored_template(template_id: int) -> str:
    db = get_db_session()
    try:
        record = TemplatesService(db).get_template(template_id)
    except TemplateNotFoundError as exc:
        raise ValueError(
            f"render-jinja-template: stored template {template_id} was not found"
        ) from exc
    finally:
        db.close()
    return str(record.get("content") or "")


def _resolve_template(config: dict[str, Any]) -> str:
    """Resolve the Jinja2 template body for this step.

    A stored template (referenced by ``template_id``) is the source of truth.
    An inline ``template`` string is only accepted as a fallback for legacy
    nodes created before the template library existed.
    """
    raw_id = config.get("template_id")
    if raw_id not in (None, ""):
        try:
            template_id = int(raw_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "render-jinja-template: template_id must be an integer"
            ) from exc
        template = _load_stored_template(template_id).strip()
        if not template:
            raise ValueError(
                f"render-jinja-template: stored template {template_id} has no content"
            )
        validate_jinja_template(template)
        return template

    legacy_inline = str(config.get("template") or "").strip()
    if legacy_inline:
        validate_jinja_template(legacy_inline)
        return legacy_inline

    raise ValueError("render-jinja-template: a stored template must be selected")


async def _resolve_command_result(
    result: CommandResult,
    artifact_service: ArtifactService,
) -> dict[str, Any]:
    raw = ""
    parsed: Any = None
    if result.output_ref is not None:
        raw = await artifact_service.resolve(result.output_ref)
        if result.output_ref.media_type == "application/json":
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None
    return {
        "node_id": result.node_id,
        "name": result.command,
        "success": result.success,
        "raw": raw,
        "parsed": parsed,
    }


async def _build_command_context(
    device: DeviceContext,
    artifact_service: ArtifactService,
) -> dict[str, Any]:
    """Resolve upstream run-command output into the Jinja namespace.

    Exposes every command executed by any upstream run-command step as
    ``commands`` (in execution order), plus a ``command`` alias for the
    most recently executed one, covering the common single-command case.
    """
    all_results = [
        result for results in device.command_results.values() for result in results
    ]
    if not all_results:
        return {}

    entries = await asyncio.gather(
        *(_resolve_command_result(result, artifact_service) for result in all_results)
    )
    latest_index = max(
        range(len(all_results)), key=lambda i: all_results[i].executed_at
    )
    return {"commands": list(entries), "command": entries[latest_index]}


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
    template = _resolve_template(config)

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
            jinja_context.update(
                await _build_command_context(device, artifact_service)
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
            logger.warning(
                "render-jinja-template failed run_id=%s node_id=%s device_id=%s error=%s",
                run.id,
                node_id,
                device_id,
                exc,
            )
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
            logger.warning(
                "render-jinja-template failed run_id=%s node_id=%s device_id=%s error=%s",
                run.id,
                node_id,
                device_id,
                exc,
            )
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

    logger.info(
        "render-jinja-template finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )

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
