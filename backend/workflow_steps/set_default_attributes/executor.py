"""Executor for the set-default-attributes step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import Capability, DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_defaults import (
    merge_nautobot_defaults,
    normalize_defaults_block,
)
from workflow_steps.common.git_yaml_source import load_yaml_from_git_source

logger = logging.getLogger(__name__)

_STEP_ID = "set-default-attributes"
_SUPPORTED_TYPES = frozenset({"device"})
_NAMED_REFERENCE_FIELDS = ("role", "status", "location", "platform", "rack")
_SCALAR_FIELDS = ("software_version", "serial", "asset_tag", "face", "position")


def _enabled_value(spec: Any) -> str | None:
    if not isinstance(spec, dict) or not spec.get("enabled"):
        return None
    value = str(spec.get("value") or "").strip()
    return value or None


def _defaults_from_manual_config(attributes: dict[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = {}

    for key in (*_NAMED_REFERENCE_FIELDS, *_SCALAR_FIELDS, "tags"):
        value = _enabled_value(attributes.get(key))
        if value is not None:
            raw[key] = value

    device_type_spec = attributes.get("device_type")
    if isinstance(device_type_spec, dict) and device_type_spec.get("enabled"):
        model = str(device_type_spec.get("model") or "").strip()
        manufacturer = str(device_type_spec.get("manufacturer") or "").strip()
        if model or manufacturer:
            raw["device_type"] = {
                "model": model,
                "manufacturer": {"name": manufacturer} if manufacturer else {},
            }

    custom_fields_spec = attributes.get("custom_fields")
    if isinstance(custom_fields_spec, dict):
        custom_fields = {
            name: _enabled_value(spec)
            for name, spec in custom_fields_spec.items()
            if _enabled_value(spec) is not None
        }
        if custom_fields:
            raw["custom_fields"] = custom_fields

    interfaces_spec = attributes.get("interfaces")
    if isinstance(interfaces_spec, list):
        raw["interfaces"] = interfaces_spec

    return raw


def _defaults_from_git(config: dict[str, Any]) -> dict[str, Any]:
    git_config = config.get("git") or {}
    git_source_id = str(git_config.get("git_source_id") or "").strip()
    filename_pattern = str(git_config.get("filename_pattern") or "").strip()

    parsed = load_yaml_from_git_source(
        git_source_id=git_source_id,
        filename_pattern=filename_pattern,
        step_id=_STEP_ID,
    )
    devices_block = parsed.get("devices") if isinstance(parsed, dict) else None
    if not isinstance(devices_block, dict):
        raise ValueError(f"{_STEP_ID}: YAML file must contain a top-level 'devices' mapping")
    return devices_block


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    resource_type = str(config.get("type") or "device").strip().lower()
    if resource_type not in _SUPPORTED_TYPES:
        raise ValueError(
            f"{_STEP_ID}: type '{resource_type}' is not yet supported (only 'device')"
        )

    overwrite = bool(config.get("overwrite", False))
    mode = str(config.get("mode") or "manual").strip().lower()

    if mode == "manual":
        raw_defaults = _defaults_from_manual_config(config.get("attributes") or {})
    elif mode == "git":
        raw_defaults = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _defaults_from_git(config)
        )
    else:
        raise ValueError(f"{_STEP_ID}: mode must be 'manual' or 'git', got {mode!r}")

    defaults = normalize_defaults_block(raw_defaults)

    logger.info(
        "%s started run_id=%s node_id=%s mode=%s overwrite=%s devices=%d",
        _STEP_ID,
        run.id,
        node_id,
        mode,
        overwrite,
        len(context.devices),
    )

    if not context.devices or not defaults:
        logger.info("%s finished (no-op) run_id=%s", _STEP_ID, run.id)
        return [StepOutcome(name="success", context=context)]

    updated_devices: dict[str, DeviceContext] = {}
    for device_id, device in context.devices.items():
        existing_bag = device.attribute_bags.get("nautobot")
        merged_bag = merge_nautobot_defaults(existing_bag, defaults, overwrite=overwrite)
        updated_devices[device_id] = device.model_copy(
            update={
                "attribute_bags": {**device.attribute_bags, "nautobot": merged_bag},
                "capabilities": device.capabilities | {Capability.ATTRIBUTES},
            }
        )

    logger.info(
        "%s finished run_id=%s devices_updated=%d",
        _STEP_ID,
        run.id,
        len(updated_devices),
    )

    new_context = context.model_copy(update={"devices": updated_devices})
    return [StepOutcome(name="success", context=new_context)]
