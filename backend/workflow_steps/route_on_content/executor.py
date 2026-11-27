"""Executor for the route-on-content control-flow step."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.ai_assistant.redaction import Redactor
from services.artifacts import ArtifactService
from services.workflow_context.node_result import set_node_result
from workflow_steps.common.content_resolver import (
    AMBIGUOUS_CONTENT_FAILURE,
    ambiguous_content_message,
    list_exportable_content,
    parse_content_source,
)
from workflow_steps.common.failure_records import INVALID_INPUT, MISSING_DATA, REGEX_STOPPED
from workflow_steps.common.partial_outcomes import device_error_from_exception
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.common.regex_search import RegexAnswer, RegexQuestion, search_many
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.route_on_content.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)
_STEP_ID = "route-on-content"

_OUTCOME_NAMES = ("match", "mismatch", "failure")
_MATCH_MODES = frozenset({"fixed_text", "regex"})
_MATCHED_TEXT_MAX_LENGTH = 200


@dataclass(frozen=True)
class _ParsedRouteConfig:
    content_source: str
    source_step_node_id: str | None
    parsed_output_key: str | None
    match_mode: str
    pattern: str
    case_sensitive: bool
    multiline: bool
    store_matched_text: bool = False


@dataclass(frozen=True)
class _Ready:
    """A device whose regex still has to be answered by the isolated worker."""

    device_id: str
    device: DeviceContext
    rendered_pattern: str
    content_text: str = field(repr=False)


def _parse_route_config(config: dict[str, Any]) -> _ParsedRouteConfig:
    content_source = parse_content_source(
        config, step_id=_STEP_ID, default=str(get_config()["content_source"])
    )
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None

    match_mode = str(config.get("match_mode") or get_config()["match_mode"]).strip().lower()
    if match_mode not in _MATCH_MODES:
        raise ValueError(
            f"route-on-content: match_mode {match_mode!r} must be one of {sorted(_MATCH_MODES)}"
        )

    pattern = str(config.get("pattern") or "").strip()
    if not pattern:
        raise ValueError("route-on-content: pattern is required")

    return _ParsedRouteConfig(
        content_source=content_source,
        source_step_node_id=source_step_node_id,
        parsed_output_key=parsed_output_key,
        match_mode=match_mode,
        pattern=pattern,
        case_sensitive=parse_bool_flag(config, "case_sensitive", default=False),
        multiline=parse_bool_flag(config, "multiline", default=False),
        store_matched_text=parse_bool_flag(config, "store_matched_text", default=False),
    )


def _match_fixed_text(
    content_text: str, pattern: str, *, case_sensitive: bool
) -> tuple[bool, str | None]:
    haystack = content_text if case_sensitive else content_text.casefold()
    needle = pattern if case_sensitive else pattern.casefold()
    if needle in haystack:
        return True, pattern[:_MATCHED_TEXT_MAX_LENGTH]
    return False, None


def _matched_text_entry(parsed: _ParsedRouteConfig, matched_text: str | None) -> dict[str, str]:
    """The matched text for the stored result, only when the author asked for it (W10-02).

    ``parsed`` is persisted with every step result and shown to everyone who may read runs, and a
    pattern that asks "is a key set?" matches the line that holds it. So the text is off by
    default and, when on, goes through the config-secret redactor first.
    """
    if not parsed.store_matched_text or matched_text is None:
        return {}
    return {"matched_text": Redactor().redact(matched_text)}


def _device_failure(
    *,
    device: DeviceContext,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
) -> DeviceContext:
    err = DeviceError(
        node_id=node_id, step_id=_STEP_ID, code=code, message=message, failure=failure
    )
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


async def _prepare_device(
    *,
    device_id: str,
    device: DeviceContext,
    parsed: _ParsedRouteConfig,
    node_id: str,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, str] | _Ready:
    """Read the content and render the pattern; a regex match is answered later, in a batch."""
    export_items = list_exportable_content(
        device,
        content_source=parsed.content_source,
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
        step_id=_STEP_ID,
    )
    if not export_items:
        failed = _device_failure(
            device=device,
            node_id=node_id,
            code="missing_content",
            failure=MISSING_DATA,
            message=(
                f"No {parsed.content_source!r} content available for device {device_id}. "
                "Ensure an upstream step produced the selected data."
            ),
        )
        return device_id, failed, "failure"

    if len(export_items) > 1:
        failed = _device_failure(
            device=device,
            node_id=node_id,
            code="ambiguous_content",
            message=ambiguous_content_message(len(export_items)),
            failure=AMBIGUOUS_CONTENT_FAILURE,
        )
        return device_id, failed, "failure"
    item = export_items[0]

    try:
        content_text = await artifact_service.resolve(item.artifact_ref)
    except Exception as exc:  # noqa: BLE001 - surfaced as a per-device failure below
        err = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
        failed = _device_failure(
            device=device,
            node_id=node_id,
            code="content_unavailable",
            message=err.message,
            failure=err.failure,
        )
        return device_id, failed, "failure"

    rendered_pattern = render_placeholder_template(
        parsed.pattern,
        device,
        value_transform=re.escape if parsed.match_mode == "regex" else None,
    )
    if not rendered_pattern:
        failed = _device_failure(
            device=device,
            node_id=node_id,
            code="pattern_unresolved",
            failure=INVALID_INPUT,
            message=(
                "pattern rendered to an empty string for this device — a "
                "{path.to.attribute} placeholder may not have resolved"
            ),
        )
        return device_id, failed, "failure"

    if parsed.match_mode == "regex":
        return _Ready(
            device_id=device_id,
            device=device,
            rendered_pattern=rendered_pattern,
            content_text=content_text,
        )
    matched, matched_text = _match_fixed_text(
        content_text, rendered_pattern, case_sensitive=parsed.case_sensitive
    )
    return _finish(
        device_id=device_id,
        device=device,
        parsed=parsed,
        node_id=node_id,
        matched=matched,
        matched_text=matched_text,
    )


def _finish(
    *,
    device_id: str,
    device: DeviceContext,
    parsed: _ParsedRouteConfig,
    node_id: str,
    matched: bool,
    matched_text: str | None,
) -> tuple[str, DeviceContext, str]:
    device_parsed = set_node_result(
        device.parsed,
        node_id,
        "content_match",
        {
            "kind": "content_match_result",
            "matched": matched,
            "content_source": parsed.content_source,
            "match_mode": parsed.match_mode,
            "case_sensitive": parsed.case_sensitive,
            "multiline": parsed.multiline,
            **_matched_text_entry(parsed, matched_text),
        },
    )
    enriched = device.model_copy(
        update={
            "parsed": device_parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
        }
    )
    return device_id, enriched, "match" if matched else "mismatch"


def _answer_regex(
    ready: _Ready, answer: RegexAnswer, *, parsed: _ParsedRouteConfig, node_id: str
) -> tuple[str, DeviceContext, str]:
    if answer.status in ("invalid", "stopped"):
        stopped = answer.status == "stopped"
        failed = _device_failure(
            device=ready.device,
            node_id=node_id,
            code="regex_stopped" if stopped else "invalid_regex",
            failure=REGEX_STOPPED if stopped else INVALID_INPUT,
            message=(
                f"the regular expression {ready.rendered_pattern!r} was stopped: it used too "
                "much time or memory on this content"
                if stopped
                else f"invalid regular expression {ready.rendered_pattern!r}"
            ),
        )
        return ready.device_id, failed, "failure"
    return _finish(
        device_id=ready.device_id,
        device=ready.device,
        parsed=parsed,
        node_id=node_id,
        matched=answer.found,
        matched_text=answer.match,
    )


def _build_route_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    results: list[tuple[str, DeviceContext, str]],
) -> list[StepOutcome]:
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


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del run

    parsed = _parse_route_config(config)
    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    logger.info(
        "route-on-content started run_id=%s node_id=%s content_source=%s match_mode=%s",
        context.run_id,
        node_id,
        parsed.content_source,
        parsed.match_mode,
    )

    prepared = await asyncio.gather(
        *[
            _prepare_device(
                device_id=device_id,
                device=device,
                parsed=parsed,
                node_id=node_id,
                artifact_service=artifact_service,
            )
            for device_id, device in context.devices.items()
        ]
    )
    ready = [item for item in prepared if isinstance(item, _Ready)]
    # The author's pattern never runs in this process: ``re`` holds the GIL while it matches.
    answers = await search_many(
        [RegexQuestion(text=r.content_text, pattern=r.rendered_pattern) for r in ready],
        ignore_case=not parsed.case_sensitive,
        multiline=parsed.multiline,
        max_text=_MATCHED_TEXT_MAX_LENGTH,
    )
    answered = {
        id(r): _answer_regex(r, a, parsed=parsed, node_id=node_id)
        for r, a in zip(ready, answers, strict=True)
    }
    results = [answered[id(item)] if isinstance(item, _Ready) else item for item in prepared]
    return _build_route_outcomes(context=context, node_id=node_id, results=results)
