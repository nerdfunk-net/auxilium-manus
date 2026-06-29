"""Executor for the compare-data step."""

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

logger = logging.getLogger(__name__)

_OUTCOME_NAMES = ("match", "mismatch", "failure")


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_bool(config: dict[str, Any], key: str, *, default: bool = False) -> bool:
    value = config.get(key, _default_config().get(key, default))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


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


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    if not context.devices:
        return [
            StepOutcome(
                name=outcome_name,
                context=context,
            )
            for outcome_name in _OUTCOME_NAMES
        ]

    content_source = parse_content_source(config)
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None
    reference_location = str(
        config.get("reference_location")
        or _default_config().get("reference_location")
        or "filesystem"
    ).strip().lower()
    normalize_line_endings = _parse_bool(
        config, "normalize_line_endings", default=True
    )
    ignore_trailing_whitespace = _parse_bool(
        config, "ignore_trailing_whitespace", default=False
    )
    diff_service = GitDiffService()

    logger.info(
        "compare-data run_id=%s devices=%d source=%s reference=%s",
        run.id,
        len(context.devices),
        content_source,
        reference_location,
    )

    buckets: dict[str, dict[str, DeviceContext]] = {
        "match": {},
        "mismatch": {},
        "failure": {},
    }
    comparison_records: list[dict[str, Any]] = []

    async def compare_for_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, str, dict[str, Any] | None]:
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
            return device_id, failed, "failure", None

        item = export_items[0]
        if len(export_items) > 1:
            logger.warning(
                "compare-data device=%s source=%s has %d export items; using first only",
                device_id,
                content_source,
                len(export_items),
            )

        try:
            source_content = await artifact_service.resolve(item.artifact_ref)
            reference_path = _render_reference_path(
                device=device,
                item=item,
                config=config,
                run_id=context.run_id,
            )
            reference_content = await read_reference_text(
                config=config,
                relative_path=reference_path,
            )
        except Exception as exc:
            failed = _device_failure(device=device, node_id=node_id, message=str(exc))
            return device_id, failed, "failure", None

        normalized_source = _normalize_text(
            source_content,
            normalize_line_endings=normalize_line_endings,
            ignore_trailing_whitespace=ignore_trailing_whitespace,
        )
        normalized_reference = _normalize_text(
            reference_content,
            normalize_line_endings=normalize_line_endings,
            ignore_trailing_whitespace=ignore_trailing_whitespace,
        )
        matched = normalized_source == normalized_reference

        parsed = dict(device.parsed)
        capabilities = set(device.capabilities)
        record: dict[str, Any] = {
            "device_id": device_id,
            "content_source": content_source,
            "reference_location": reference_location,
            "reference_path": reference_path,
            "matched": matched,
            **item.extra,
        }

        if matched:
            parsed[f"{node_id}.comparison"] = _comparison_result_entry(
                matched=True,
                content_source=content_source,
                reference_path=reference_path,
                reference_location=reference_location,
                node_id=node_id,
                item_extra=item.extra,
            )
            capabilities.add(Capability.PARSED)
            enriched = device.model_copy(
                update={
                    "parsed": parsed,
                    "capabilities": capabilities,
                    "status": DeviceStatus.OK,
                }
            )
            return device_id, enriched, "match", record

        diff_result = diff_service.compare_text_content(
            normalized_source,
            normalized_reference,
        )
        diff_text = "\n".join(diff_result.diff_lines)
        diff_ref = await artifact_service.store(
            content=diff_text,
            kind="comparison_diff",
            device_id=device_id,
            run_id=context.run_id,
            media_type="text/plain",
        )
        diff_stats = {
            "additions": diff_result.stats.additions,
            "deletions": diff_result.stats.deletions,
        }
        comparison_diff_key = f"{node_id}.comparison_diff"
        parsed[comparison_diff_key] = _comparison_diff_entry(
            artifact_ref=diff_ref,
            content_source=content_source,
            reference_path=reference_path,
            reference_location=reference_location,
            node_id=node_id,
            item_extra=item.extra,
            diff_stats=diff_stats,
        )
        parsed[f"{node_id}.comparison"] = _comparison_result_entry(
            matched=False,
            content_source=content_source,
            reference_path=reference_path,
            reference_location=reference_location,
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
                "parsed": parsed,
                "capabilities": capabilities,
                "status": DeviceStatus.OK,
            }
        )
        return device_id, enriched, "mismatch", record

    results = await asyncio.gather(
        *[
            compare_for_device(device_id, device)
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
