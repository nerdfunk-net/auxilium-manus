"""Executor for the route-on-content control-flow step."""

from __future__ import annotations

import asyncio
import logging
import re
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
from workflow_steps.common.content_resolver import list_exportable_content, parse_content_source
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.route_on_content.config import get_config

logger = logging.getLogger(__name__)

_OUTCOME_NAMES = ("match", "mismatch", "failure")
_MATCH_MODES = frozenset({"fixed_text", "regex"})
_MATCHED_TEXT_MAX_LENGTH = 200


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_bool(config: dict[str, Any], key: str, *, default: bool = False) -> bool:
    value = config.get(key, _default_config().get(key, default))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _match_fixed_text(
    content_text: str, pattern: str, *, case_sensitive: bool
) -> tuple[bool, str | None]:
    haystack = content_text if case_sensitive else content_text.casefold()
    needle = pattern if case_sensitive else pattern.casefold()
    if needle in haystack:
        return True, pattern[:_MATCHED_TEXT_MAX_LENGTH]
    return False, None


def _match_regex(
    content_text: str, pattern: str, *, case_sensitive: bool, multiline: bool
) -> tuple[bool, str | None]:
    flags = 0
    if multiline:
        flags |= re.MULTILINE
    if not case_sensitive:
        flags |= re.IGNORECASE
    found = re.compile(pattern, flags).search(content_text)
    if found is None:
        return False, None
    return True, found.group(0)[:_MATCHED_TEXT_MAX_LENGTH]


def _device_failure(
    *, device: DeviceContext, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id="route-on-content", code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del run

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    content_source = parse_content_source(
        {
            "content_source": str(
                config.get("content_source") or _default_config()["content_source"]
            )
        }
    )
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None

    match_mode = str(
        config.get("match_mode") or _default_config()["match_mode"]
    ).strip().lower()
    if match_mode not in _MATCH_MODES:
        raise ValueError(
            f"route-on-content: match_mode {match_mode!r} must be one of "
            f"{sorted(_MATCH_MODES)}"
        )

    pattern = str(config.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("route-on-content: pattern is required")

    case_sensitive = _parse_bool(config, "case_sensitive", default=False)
    multiline = _parse_bool(config, "multiline", default=False)

    logger.info(
        "route-on-content started run_id=%s node_id=%s content_source=%s match_mode=%s",
        context.run_id,
        node_id,
        content_source,
        match_mode,
    )

    async def process_device(
        device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, str]:
        export_items = list_exportable_content(
            device,
            content_source=content_source,
            source_step_node_id=source_step_node_id,
            parsed_output_key=parsed_output_key,
        )
        if not export_items:
            failed = _device_failure(
                device=device,
                node_id=node_id,
                code="missing_content",
                message=(
                    f"No {content_source!r} content available for device {device_id}. "
                    "Ensure an upstream step produced the selected data."
                ),
            )
            return device_id, failed, "failure"

        item = export_items[0]
        if len(export_items) > 1:
            logger.warning(
                "route-on-content device=%s source=%s has %d export items; using first only",
                device_id,
                content_source,
                len(export_items),
            )

        try:
            content_text = await artifact_service.resolve(item.artifact_ref)
        except Exception as exc:  # noqa: BLE001 - surfaced as a per-device failure below
            failed = _device_failure(
                device=device,
                node_id=node_id,
                code="content_unavailable",
                message=str(exc),
            )
            return device_id, failed, "failure"

        rendered_pattern = render_placeholder_template(
            pattern,
            device,
            value_transform=re.escape if match_mode == "regex" else None,
        )
        if not rendered_pattern:
            failed = _device_failure(
                device=device,
                node_id=node_id,
                code="pattern_unresolved",
                message=(
                    "pattern rendered to an empty string for this device — a "
                    "{path.to.attribute} placeholder may not have resolved"
                ),
            )
            return device_id, failed, "failure"

        try:
            if match_mode == "fixed_text":
                matched, matched_text = _match_fixed_text(
                    content_text, rendered_pattern, case_sensitive=case_sensitive
                )
            else:
                matched, matched_text = _match_regex(
                    content_text,
                    rendered_pattern,
                    case_sensitive=case_sensitive,
                    multiline=multiline,
                )
        except re.error as exc:
            failed = _device_failure(
                device=device,
                node_id=node_id,
                code="invalid_regex",
                message=f"invalid regular expression {rendered_pattern!r}: {exc}",
            )
            return device_id, failed, "failure"

        parsed = dict(device.parsed)
        parsed[f"{node_id}.content_match"] = {
            "kind": "content_match_result",
            "matched": matched,
            "content_source": content_source,
            "match_mode": match_mode,
            "case_sensitive": case_sensitive,
            "multiline": multiline,
            **({"matched_text": matched_text} if matched_text is not None else {}),
        }
        enriched = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
                "status": DeviceStatus.OK,
            }
        )
        return device_id, enriched, "match" if matched else "mismatch"

    results = await asyncio.gather(
        *[process_device(device_id, device) for device_id, device in context.devices.items()]
    )

    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in _OUTCOME_NAMES}
    for device_id, updated_device, bucket_name in results:
        buckets[bucket_name][device_id] = updated_device

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.content_match_counts": counts}

    logger.info(
        "route-on-content finished run_id=%s node_id=%s counts=%s",
        context.run_id,
        node_id,
        counts,
    )

    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]
