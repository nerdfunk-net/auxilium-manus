"""Executor for the update-content step.

Reads a device's running or startup config, applies an ordered list of regex
search/replace rules to the text (bulk `re.sub`-style, not single-match extraction),
and stores the result as a new `updated_content` artifact so downstream steps
(store-artifact, and future upload/verify steps) can consume it via
`workflow_steps/common/content_resolver.py`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.workflow_context.attribute_regex import (
    RegexFlagsConfig,
    apply_regex_content_replace,
    compile_pattern,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-content"
_SUPPORTED_SOURCES = frozenset({"running_config", "startup_config"})


@dataclass(frozen=True)
class _ReplaceRule:
    pattern: str
    replacement: str
    regex_flags: RegexFlagsConfig
    replace_all: bool


@dataclass(frozen=True)
class _ParsedUpdateContentConfig:
    content_source: str
    rules: list[_ReplaceRule]


def _parse_content_source(config: dict[str, Any]) -> str:
    source = str(config.get("content_source") or "running_config").strip().lower()
    if source not in _SUPPORTED_SOURCES:
        raise ValueError(
            f"update-content: content_source {source!r} must be one of {sorted(_SUPPORTED_SOURCES)}"
        )
    return source


def _parse_replace_all(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    if value is None:
        return True
    return bool(value)


def _parse_rules(config: dict[str, Any]) -> list[_ReplaceRule]:
    raw = config.get("replace_rules")
    if not raw:
        raise ValueError("update-content: at least one rule in replace_rules is required")
    if not isinstance(raw, list):
        raise ValueError("update-content: replace_rules must be a list")

    rules: list[_ReplaceRule] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"update-content: replace_rules[{i}] must be a dict")
        pattern = str(item.get("pattern") or "").strip()
        if not pattern:
            raise ValueError(f"update-content: replace_rules[{i}].pattern is required")
        regex_flags = RegexFlagsConfig.from_mapping(item.get("regex_flags"))
        try:
            compile_pattern(pattern, regex_flags)
        except ValueError as exc:
            raise ValueError(f"update-content: replace_rules[{i}].{exc}") from exc
        rules.append(
            _ReplaceRule(
                pattern=pattern,
                replacement=str(item.get("replacement") or ""),
                regex_flags=regex_flags,
                replace_all=_parse_replace_all(item.get("replace_all")),
            )
        )
    return rules


def _parse_update_content_config(config: dict[str, Any]) -> _ParsedUpdateContentConfig:
    return _ParsedUpdateContentConfig(
        content_source=_parse_content_source(config),
        rules=_parse_rules(config),
    )


def _source_ref(device: DeviceContext, content_source: str) -> ArtifactRef | None:
    if content_source == "running_config":
        return device.running_config_ref
    return device.startup_config_ref


def _apply_rules_to_text(text: str, rules: list[_ReplaceRule]) -> tuple[str, list[int]]:
    match_counts: list[int] = []
    current = text
    for rule in rules:
        current, match_count = apply_regex_content_replace(
            source_text=current,
            pattern=rule.pattern,
            replacement=rule.replacement,
            flags=rule.regex_flags,
            replace_all=rule.replace_all,
        )
        match_counts.append(match_count)
    return current, match_counts


async def _update_and_store(
    *,
    source_ref: ArtifactRef,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    run_id: str | None,
    parsed: _ParsedUpdateContentConfig,
    artifact_service: ArtifactService,
) -> DeviceContext:
    raw_content = await artifact_service.resolve(source_ref)
    updated_text, match_counts = _apply_rules_to_text(raw_content, parsed.rules)

    artifact_ref = await artifact_service.store(
        content=updated_text,
        kind="updated_content",
        device_id=device_id,
        run_id=run_id,
        media_type=source_ref.media_type,
    )

    size_bytes = len(updated_text.encode("utf-8"))
    updated_parsed = {
        **device.parsed,
        f"{node_id}.updated_content": {
            "artifact_ref": artifact_ref.model_dump(mode="json"),
            "step_node_id": node_id,
            "output_key": "updated_content",
            "size_bytes": size_bytes,
            "kind": "updated_content",
            "match_counts": match_counts,
        },
    }

    return device.model_copy(
        update={
            "parsed": updated_parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
        }
    )


async def _update_device(
    *,
    device_id: str,
    device: DeviceContext,
    parsed: _ParsedUpdateContentConfig,
    node_id: str,
    run_id: str | None,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, bool]:
    try:
        source_ref = _source_ref(device, parsed.content_source)
        if source_ref is None:
            raise ValueError(
                f"{parsed.content_source} is not available on this device — add a "
                "Get Configs step upstream of update-content"
            )
        enriched = await _update_and_store(
            source_ref=source_ref,
            device_id=device_id,
            device=device,
            node_id=node_id,
            run_id=run_id,
            parsed=parsed,
            artifact_service=artifact_service,
        )
        return device_id, enriched, True

    except Exception as exc:
        logger.warning("update-content device=%s error=%s", device_id, exc)
        err = DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
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


def _partition_device_results(
    results: list[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device
    return success_devices, failed_devices


def _build_update_content_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    metadata = {
        **context.metadata,
        f"{node_id}.update_content_success_count": len(success_devices),
        f"{node_id}.update_content_failure_count": len(failed_devices),
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
                context=context.model_copy(
                    update={"devices": failed_devices, "metadata": metadata}
                ),
            )
        )
    return outcomes


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    parsed = _parse_update_content_config(config)
    logger.info(
        "update-content started run_id=%s node_id=%s devices=%d content_source=%s rules=%d",
        run.id,
        node_id,
        len(context.devices),
        parsed.content_source,
        len(parsed.rules),
    )

    results = await asyncio.gather(
        *[
            _update_device(
                device_id=device_id,
                device=device,
                parsed=parsed,
                node_id=node_id,
                run_id=context.run_id,
                artifact_service=artifact_service,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition_device_results(results)
    logger.info(
        "update-content finished success=%d failure=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        run.id,
    )
    return _build_update_content_outcomes(
        context=context,
        node_id=node_id,
        success_devices=success_devices,
        failed_devices=failed_devices,
    )
