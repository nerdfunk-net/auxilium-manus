"""Executor for the update-attribute workflow step."""

from __future__ import annotations

import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.common.attribute_regex import RegexFlagsConfig, apply_regex_transform
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.update_attribute.config import get_config

logger = logging.getLogger(__name__)

_STEP_ID = "update-attribute"
_VALID_MODES = frozenset({"fixed", "regex"})


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("mode") or _default_config()["mode"]).strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"{_STEP_ID}: mode must be 'fixed' or 'regex'")
    return mode


def _parse_destination_path(config: dict[str, Any]) -> str:
    destination_path = str(
        config.get("destination_path") or _default_config()["destination_path"]
    ).strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")
    return destination_path


def _parse_regex_flags(config: dict[str, Any]) -> RegexFlagsConfig:
    return RegexFlagsConfig.from_mapping(
        config.get("regex_flags", _default_config()["regex_flags"])
    )


def _apply_fixed_update(
    *,
    device: DeviceContext,
    destination_path: str,
    fixed_value: str,
) -> DeviceContext:
    value = str(fixed_value)
    if not value.strip():
        raise ValueError(f"{_STEP_ID}: fixed_value is required in fixed mode")
    return set_device_attribute(device, destination_path, value)


def _apply_regex_update(
    *,
    device: DeviceContext,
    source_path: str,
    destination_path: str,
    pattern: str,
    destination_template: str,
    regex_flags: RegexFlagsConfig,
) -> DeviceContext | None:
    source_path = source_path.strip()
    pattern = pattern.strip()
    destination_template = str(destination_template)
    if not source_path:
        raise ValueError(f"{_STEP_ID}: source_path is required in regex mode")
    if not pattern:
        raise ValueError(f"{_STEP_ID}: pattern is required in regex mode")
    if not destination_template.strip():
        raise ValueError(f"{_STEP_ID}: destination_template is required in regex mode")

    source_value = resolve_device_attribute(device, source_path)
    if source_value is None:
        return None

    transformed = apply_regex_transform(
        source_text=source_value,
        pattern=pattern,
        destination_template=destination_template,
        flags=regex_flags,
    )
    if transformed is None:
        return None

    return set_device_attribute(device, destination_path, transformed)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del run, artifact_service

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    mode = _parse_mode(config)
    destination_path = _parse_destination_path(config)
    regex_flags = _parse_regex_flags(config)

    updated_devices: dict[str, DeviceContext] = {}
    skipped_count = 0
    updated_count = 0

    for device_id, device in context.devices.items():
        try:
            if mode == "fixed":
                fixed_value = str(config.get("fixed_value") or "")
                updated_devices[device_id] = _apply_fixed_update(
                    device=device,
                    destination_path=destination_path,
                    fixed_value=fixed_value,
                )
                updated_count += 1
                continue

            source_path = str(config.get("source_path") or _default_config()["source_path"])
            pattern = str(config.get("pattern") or "")
            destination_template = str(
                config.get("destination_template") or _default_config()["destination_template"]
            )
            updated = _apply_regex_update(
                device=device,
                source_path=source_path,
                destination_path=destination_path,
                pattern=pattern,
                destination_template=destination_template,
                regex_flags=regex_flags,
            )
            if updated is None:
                updated_devices[device_id] = device
                skipped_count += 1
                continue

            updated_devices[device_id] = updated
            updated_count += 1
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(f"{_STEP_ID}: failed for device {device_id}: {exc}") from exc

    metadata = {
        **context.metadata,
        f"{node_id}.mode": mode,
        f"{node_id}.destination_path": destination_path,
        f"{node_id}.updated_count": updated_count,
        f"{node_id}.skipped_count": skipped_count,
    }
    if mode == "regex":
        metadata[f"{node_id}.source_path"] = str(
            config.get("source_path") or _default_config()["source_path"]
        ).strip()

    logger.info(
        "%s node_id=%s mode=%s destination_path=%s updated=%d skipped=%d devices=%d",
        _STEP_ID,
        node_id,
        mode,
        destination_path,
        updated_count,
        skipped_count,
        len(context.devices),
    )

    return [
        StepOutcome(
            name="success",
            context=context.model_copy(
                update={
                    "devices": updated_devices,
                    "metadata": metadata,
                }
            ),
        )
    ]
