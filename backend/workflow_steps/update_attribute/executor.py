"""Executor for the update-attribute workflow step."""

from __future__ import annotations

import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    path_is_known_secret,
    seal_secret,
)
from workflow_steps.common.attribute_path import resolve_device_attribute
from workflow_steps.common.attribute_regex import RegexFlagsConfig, apply_regex_transform
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.update_attribute.config import get_default_attribute

logger = logging.getLogger(__name__)

_STEP_ID = "update-attribute"
_VALID_MODES = frozenset({"fixed", "regex"})


def _default_attribute() -> dict[str, Any]:
    return get_default_attribute()


def _parse_mode(raw: Any) -> str:
    mode = str(raw or _default_attribute()["mode"]).strip().lower()
    if mode not in _VALID_MODES:
        raise ValueError(f"{_STEP_ID}: mode must be 'fixed' or 'regex'")
    return mode


def _parse_destination_path(raw: Any) -> str:
    destination_path = str(raw or _default_attribute()["destination_path"]).strip()
    if not destination_path:
        raise ValueError(f"{_STEP_ID}: destination_path is required")
    return destination_path


def _parse_regex_flags(raw: Any) -> RegexFlagsConfig:
    return RegexFlagsConfig.from_mapping(
        raw if raw is not None else _default_attribute()["regex_flags"]
    )


def _normalize_attribute_entry(raw: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{_STEP_ID}: attributes[{index}] must be an object")

    defaults = _default_attribute()
    mode = _parse_mode(raw.get("mode", defaults["mode"]))
    destination_path = _parse_destination_path(
        raw.get("destination_path", defaults["destination_path"])
    )
    return {
        "mode": mode,
        "destination_path": destination_path,
        "fixed_value": str(raw.get("fixed_value", defaults["fixed_value"])),
        "source_path": str(raw.get("source_path", defaults["source_path"])),
        "pattern": str(raw.get("pattern", defaults["pattern"])),
        "destination_template": str(
            raw.get("destination_template", defaults["destination_template"])
        ),
        "regex_flags": _parse_regex_flags(raw.get("regex_flags", defaults["regex_flags"])),
    }


def _legacy_attribute_from_config(config: dict[str, Any]) -> dict[str, Any] | None:
    """Migrate pre-list configs that stored a single update at the top level."""
    has_legacy = any(
        key in config
        for key in (
            "mode",
            "destination_path",
            "fixed_value",
            "source_path",
            "pattern",
            "destination_template",
            "regex_flags",
        )
    )
    if not has_legacy:
        return None
    return _normalize_attribute_entry(config, index=0)


def _parse_attributes(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_attributes = config.get("attributes")
    if isinstance(raw_attributes, list):
        return [
            _normalize_attribute_entry(item, index=index)
            for index, item in enumerate(raw_attributes)
        ]

    legacy = _legacy_attribute_from_config(config)
    if legacy is not None:
        return [legacy]

    # Empty default from get_config() — no updates configured.
    if "attributes" in config or not config:
        return []

    raise ValueError(f"{_STEP_ID}: attributes must be a list")


def _apply_fixed_update(
    *,
    device: DeviceContext,
    destination_path: str,
    fixed_value: str,
) -> DeviceContext:
    value = str(fixed_value)
    if not value.strip():
        raise ValueError(f"{_STEP_ID}: fixed_value is required in fixed mode")
    stored_value: Any = seal_secret(value) if path_is_known_secret(destination_path) else value
    return set_device_attribute(device, destination_path, stored_value)


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

    # update-attribute is a generic power-user step, not a trusted secret
    # consumer (unlike render-jinja-template / update-ise-tacacs-key) — never
    # rehydrate a sealed value here, so it can't be regex-copied into a new
    # plaintext bag path that the redaction boundary doesn't know about.
    source_value = resolve_device_attribute(device, source_path, reveal_secrets=False)
    if source_value == REDACTED_PLACEHOLDER:
        raise ValueError(
            f"{_STEP_ID}: source_path '{source_path}' resolves to a sealed secret; "
            "update-attribute cannot read or copy secret values. Use "
            "render-jinja-template or the ISE-specific steps instead."
        )
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

    stored_value: Any = (
        seal_secret(transformed) if path_is_known_secret(destination_path) else transformed
    )
    return set_device_attribute(device, destination_path, stored_value)


def _apply_attribute_update(
    *,
    device: DeviceContext,
    attribute: dict[str, Any],
) -> tuple[DeviceContext, bool]:
    """Apply one attribute update. Returns (device, wrote)."""
    mode = attribute["mode"]
    destination_path = attribute["destination_path"]

    if mode == "fixed":
        updated = _apply_fixed_update(
            device=device,
            destination_path=destination_path,
            fixed_value=attribute["fixed_value"],
        )
        return updated, True

    updated = _apply_regex_update(
        device=device,
        source_path=attribute["source_path"],
        destination_path=destination_path,
        pattern=attribute["pattern"],
        destination_template=attribute["destination_template"],
        regex_flags=attribute["regex_flags"],
    )
    if updated is None:
        return device, False
    return updated, True


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

    attributes = _parse_attributes(config)

    logger.info(
        "%s started run_id=%s node_id=%s attribute_count=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(attributes),
    )

    updated_devices: dict[str, DeviceContext] = {}
    skipped_count = 0
    updated_count = 0
    write_count = 0

    for device_id, device in context.devices.items():
        current = device
        device_writes = 0
        try:
            for attribute in attributes:
                current, wrote = _apply_attribute_update(device=current, attribute=attribute)
                if wrote:
                    device_writes += 1
        except ValueError:
            raise
        except Exception as exc:
            raise RuntimeError(f"{_STEP_ID}: failed for device {device_id}: {exc}") from exc

        updated_devices[device_id] = current
        write_count += device_writes
        if device_writes > 0:
            updated_count += 1
        elif attributes:
            skipped_count += 1

    destination_paths = [attr["destination_path"] for attr in attributes]
    metadata = {
        **context.metadata,
        f"{node_id}.attribute_count": len(attributes),
        f"{node_id}.destination_paths": destination_paths,
        f"{node_id}.updated_count": updated_count,
        f"{node_id}.skipped_count": skipped_count,
        f"{node_id}.write_count": write_count,
    }
    # Preserve legacy single-update metadata keys when exactly one attribute is configured.
    if len(attributes) == 1:
        only = attributes[0]
        metadata[f"{node_id}.mode"] = only["mode"]
        metadata[f"{node_id}.destination_path"] = only["destination_path"]
        if only["mode"] == "regex":
            metadata[f"{node_id}.source_path"] = str(only["source_path"]).strip()

    logger.info(
        "%s finished node_id=%s attributes=%d updated=%d skipped=%d writes=%d devices=%d",
        _STEP_ID,
        node_id,
        len(attributes),
        updated_count,
        skipped_count,
        write_count,
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
