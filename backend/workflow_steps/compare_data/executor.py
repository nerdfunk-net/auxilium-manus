"""Executor for the compare-data step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

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
from services.git.diff import GitDiffService
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
from workflow_steps.compare_data.config import get_config
from workflow_steps.compare_data.reference_reader import read_reference_text

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_OUTCOME_NAMES = ("match", "mismatch", "failure")


@dataclass(frozen=True)
class _ParsedCompareConfig:
    content_source: str
    source_step_node_id: str | None
    parsed_output_key: str | None
    reference_location: str
    normalize_line_endings: bool
    ignore_trailing_whitespace: bool


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_bool(config: dict[str, Any], key: str, *, default: bool = False) -> bool:
    value = config.get(key, _default_config().get(key, default))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_compare_config(config: dict[str, Any]) -> _ParsedCompareConfig:
    return _ParsedCompareConfig(
        content_source=parse_content_source(config),
        source_step_node_id=str(config.get("source_step_node_id") or "").strip() or None,
        parsed_output_key=str(config.get("parsed_output_key") or "").strip() or None,
        reference_location=(
            str(
                config.get("reference_location")
                or _default_config().get("reference_location")
                or "filesystem"
            )
            .strip()
            .lower()
        ),
        normalize_line_endings=_parse_bool(config, "normalize_line_endings", default=True),
        ignore_trailing_whitespace=_parse_bool(config, "ignore_trailing_whitespace", default=False),
    )


def _normalize_text(
    content: str,
    *,
    normalize_line_endings: bool,
    ignore_trailing_whitespace: bool,
) -> str:
    text = content
    if normalize_line_endings:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    if ignore_trailing_whitespace:
        text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text


def _comparison_result_entry(
    *,
    matched: bool,
    content_source: str,
    reference_path: str,
    reference_location: str,
    node_id: str,
    item_extra: dict[str, Any],
    diff_stats: dict[str, int] | None = None,
    comparison_diff_key: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "kind": "comparison_result",
        "matched": matched,
        "content_source": content_source,
        "reference_location": reference_location,
        "reference_path": reference_path,
        "step_node_id": node_id,
        **item_extra,
    }
    if diff_stats is not None:
        entry["diff_stats"] = diff_stats
    if comparison_diff_key is not None:
        entry["comparison_diff_key"] = comparison_diff_key
    return entry


def _comparison_diff_entry(
    *,
    artifact_ref: Any,
    content_source: str,
    reference_path: str,
    reference_location: str,
    node_id: str,
    item_extra: dict[str, Any],
    diff_stats: dict[str, int],
) -> dict[str, Any]:
    return {
        "kind": "comparison_diff",
        "matched": False,
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "diff_stats": diff_stats,
        "content_source": content_source,
        "reference_location": reference_location,
        "reference_path": reference_path,
        "step_node_id": node_id,
        "output_key": "comparison_diff",
        **item_extra,
    }


def _device_failure(
    *,
    device: DeviceContext,
    node_id: str,
    message: str,
    code: str = "comparison_error",
) -> DeviceContext:
    err = DeviceError(
        node_id=node_id,
        step_id="compare-data",
        code=code,
        message=message,
    )
    return device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [*device.errors, err],
        }
    )


def _render_reference_path(
    *,
    device: DeviceContext,
    item: ExportableContent,
    config: dict[str, Any],
    run_id: str,
) -> str:
    template = str(
        config.get("filename_template")
        or _default_config().get("filename_template")
        or "{device.name}.cfg"
    ).strip()
    extra = dict(item.extra)
    return render_device_template(
        template,
        device,
        extra=extra,
        options=TemplateRenderOptions(
            strict=parse_strict_templates(config),
            run_id=run_id,
        ),
    )


def _resolve_compare_export_item(
    device: DeviceContext,
    device_id: str,
    parsed: _ParsedCompareConfig,
) -> ExportableContent | None:
    export_items = list_exportable_content(
        device,
        content_source=parsed.content_source,
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
    )
    if not export_items:
        return None

    item = export_items[0]
    if len(export_items) > 1:
        logger.warning(
            "compare-data device=%s source=%s has %d export items; using first only",
            device_id,
            parsed.content_source,
            len(export_items),
        )
    return item


async def _load_compare_texts(
    *,
    device: DeviceContext,
    item: ExportableContent,
    config: dict[str, Any],
    run_id: str | None,
    artifact_service: ArtifactService,
) -> tuple[str, str, str]:
    source_content = await artifact_service.resolve(item.artifact_ref)
    reference_path = _render_reference_path(
        device=device,
        item=item,
        config=config,
        run_id=run_id,
    )
    reference_content = await read_reference_text(
        config=config,
        relative_path=reference_path,
    )
    return source_content, reference_content, reference_path


def _build_compare_match_result(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    parsed: _ParsedCompareConfig,
    item: ExportableContent,
    reference_path: str,
) -> tuple[str, DeviceContext, str, dict[str, Any]]:
    device_parsed = dict(device.parsed)
    capabilities = set(device.capabilities)
    record: dict[str, Any] = {
        "device_id": device_id,
        "content_source": parsed.content_source,
        "reference_location": parsed.reference_location,
        "reference_path": reference_path,
        "matched": True,
        **item.extra,
    }
    device_parsed[f"{node_id}.comparison"] = _comparison_result_entry(
        matched=True,
        content_source=parsed.content_source,
        reference_path=reference_path,
        reference_location=parsed.reference_location,
        node_id=node_id,
        item_extra=item.extra,
    )
    capabilities.add(Capability.PARSED)
    enriched = device.model_copy(
        update={
            "parsed": device_parsed,
            "capabilities": capabilities,
            "status": DeviceStatus.OK,
        }
    )
    return device_id, enriched, "match", record


async def _build_compare_mismatch_result(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    parsed: _ParsedCompareConfig,
    item: ExportableContent,
    reference_path: str,
    normalized_source: str,
    normalized_reference: str,
    context_run_id: str | None,
    artifact_service: ArtifactService,
    diff_service: GitDiffService,
) -> tuple[str, DeviceContext, str, dict[str, Any]]:
    device_parsed = dict(device.parsed)
    capabilities = set(device.capabilities)
    record: dict[str, Any] = {
        "device_id": device_id,
        "content_source": parsed.content_source,
        "reference_location": parsed.reference_location,
        "reference_path": reference_path,
        "matched": False,
        **item.extra,
    }

    diff_result = diff_service.compare_text_content(
        normalized_source,
        normalized_reference,
    )
    diff_text = "\n".join(diff_result.diff_lines)
    diff_ref = await artifact_service.store(
        content=diff_text,
        kind="comparison_diff",
        device_id=device_id,
        run_id=context_run_id,
        media_type="text/plain",
    )
    diff_stats = {
        "additions": diff_result.stats.additions,
        "deletions": diff_result.stats.deletions,
    }
    comparison_diff_key = f"{node_id}.comparison_diff"
    device_parsed[comparison_diff_key] = _comparison_diff_entry(
        artifact_ref=diff_ref,
        content_source=parsed.content_source,
        reference_path=reference_path,
        reference_location=parsed.reference_location,
        node_id=node_id,
        item_extra=item.extra,
        diff_stats=diff_stats,
    )
    device_parsed[f"{node_id}.comparison"] = _comparison_result_entry(
        matched=False,
        content_source=parsed.content_source,
        reference_path=reference_path,
        reference_location=parsed.reference_location,
        diff_stats=diff_stats,
        comparison_diff_key=comparison_diff_key,
        node_id=node_id,
        item_extra=item.extra,
    )
    capabilities.add(Capability.PARSED)
    record["diff_stats"] = diff_stats
    record["comparison_diff_key"] = comparison_diff_key
    enriched = device.model_copy(
        update={
            "parsed": device_parsed,
            "capabilities": capabilities,
            "status": DeviceStatus.OK,
        }
    )
    return device_id, enriched, "mismatch", record


async def _compare_for_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    config: dict[str, Any],
    context_run_id: str | None,
    parsed: _ParsedCompareConfig,
    artifact_service: ArtifactService,
    diff_service: GitDiffService,
) -> tuple[str, DeviceContext, str, dict[str, Any] | None]:
    item = _resolve_compare_export_item(device, device_id, parsed)
    if item is None:
        failed = _device_failure(
            device=device,
            node_id=node_id,
            code="missing_content",
            message=(
                f"No {parsed.content_source!r} content available for device {device_id}. "
                "Ensure an upstream step produced the selected data."
            ),
        )
        return device_id, failed, "failure", None

    try:
        source_content, reference_content, reference_path = await _load_compare_texts(
            device=device,
            item=item,
            config=config,
            run_id=context_run_id,
            artifact_service=artifact_service,
        )
    except Exception as exc:
        failed = _device_failure(device=device, node_id=node_id, message=str(exc))
        return device_id, failed, "failure", None

    normalized_source = _normalize_text(
        source_content,
        normalize_line_endings=parsed.normalize_line_endings,
        ignore_trailing_whitespace=parsed.ignore_trailing_whitespace,
    )
    normalized_reference = _normalize_text(
        reference_content,
        normalize_line_endings=parsed.normalize_line_endings,
        ignore_trailing_whitespace=parsed.ignore_trailing_whitespace,
    )
    if normalized_source == normalized_reference:
        return _build_compare_match_result(
            device_id=device_id,
            device=device,
            node_id=node_id,
            parsed=parsed,
            item=item,
            reference_path=reference_path,
        )

    return await _build_compare_mismatch_result(
        device_id=device_id,
        device=device,
        node_id=node_id,
        parsed=parsed,
        item=item,
        reference_path=reference_path,
        normalized_source=normalized_source,
        normalized_reference=normalized_reference,
        context_run_id=context_run_id,
        artifact_service=artifact_service,
        diff_service=diff_service,
    )


def _build_compare_outcomes(
    *,
    context: WorkflowContext,
    buckets: dict[str, dict[str, DeviceContext]],
    metadata: dict[str, Any],
) -> list[StepOutcome]:
    return [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(
                update={
                    "devices": dict(buckets[outcome_name]),
                    "metadata": metadata,
                }
            ),
        )
        for outcome_name in _OUTCOME_NAMES
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
    if not context.devices:
        return [
            StepOutcome(
                name=outcome_name,
                context=context,
            )
            for outcome_name in _OUTCOME_NAMES
        ]

    parsed = _parse_compare_config(config)
    diff_service = GitDiffService()

    logger.info(
        "compare-data run_id=%s devices=%d source=%s reference=%s",
        run.id,
        len(context.devices),
        parsed.content_source,
        parsed.reference_location,
    )

    buckets: dict[str, dict[str, DeviceContext]] = {
        "match": {},
        "mismatch": {},
        "failure": {},
    }
    comparison_records: list[dict[str, Any]] = []

    results = await asyncio.gather(
        *[
            _compare_for_device(
                device_id=device_id,
                device=device,
                node_id=node_id,
                config=config,
                context_run_id=context.run_id,
                parsed=parsed,
                artifact_service=artifact_service,
                diff_service=diff_service,
            )
            for device_id, device in context.devices.items()
        ]
    )

    for device_id, updated_device, bucket_name, record in results:
        buckets[bucket_name][device_id] = updated_device
        if record is not None:
            comparison_records.append(record)

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = dict(context.metadata)
    metadata[f"{node_id}.comparison_counts"] = counts
    if comparison_records:
        metadata[f"{node_id}.comparisons"] = comparison_records

    logger.info(
        "compare-data run_id=%s counts=%s",
        run.id,
        counts,
    )

    return _build_compare_outcomes(context=context, buckets=buckets, metadata=metadata)
