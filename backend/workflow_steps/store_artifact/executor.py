"""Executor for the store-artifact step.

The git destination holds a per-repository advisory lock
(``services.git.repo_lock``) across the whole prepare -> per-device write ->
finalize sequence, so two concurrent callers against the same
``GitRepository`` -- fan-out children, independent sibling branches, or
separate runs -- never race on the shared working tree.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.artifacts.sinks import (
    ArtifactSink,
    FilesystemArtifactSink,
    GitArtifactSink,
    StoredExport,
)
from services.artifacts.sinks.git_sink import GitSinkPrepareError
from services.general.general_settings_service import GeneralSettingsService
from services.git.failure import GitOperationError, classify_git_exception
from services.git.scrub import scrub_url_credentials
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    parse_strict_templates,
    render_device_template,
    render_step_template,
)
from workflow_steps.common.content_resolver import (
    ExportableContent,
    list_exportable_content,
    parse_content_source,
)
from workflow_steps.common.device_outcomes import (
    build_outcomes,
    mark_device_failed,
    whole_step_failure,
)
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.git_repository_loader import load_git_repository, require_repository_id
from workflow_steps.common.partial_outcomes import device_error_from_exception
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.store_artifact.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "store-artifact"
_DESTINATIONS = frozenset({"filesystem", "git"})
# The upstream step produced nothing to store: a problem with the workflow, not a fault.
_NO_CONTENT = FailureInfo(phase="internal", kind="bad_request")


@dataclass(frozen=True)
class _ParsedStoreConfig:
    content_source: str
    source_step_node_id: str | None
    parsed_output_key: str | None


def _parse_store_config(config: dict[str, Any]) -> _ParsedStoreConfig:
    return _ParsedStoreConfig(
        content_source=parse_content_source(config, step_id=_STEP_ID),
        source_step_node_id=str(config.get("source_step_node_id") or "").strip() or None,
        parsed_output_key=str(config.get("parsed_output_key") or "").strip() or None,
    )


def _build_sink(config: dict[str, Any], *, base_dir: Path) -> ArtifactSink:
    destination = str(config.get("destination") or "filesystem").strip().lower()
    if destination not in _DESTINATIONS:
        raise ValueError(f"store-artifact: destination must be one of {sorted(_DESTINATIONS)}")
    if destination == "filesystem":
        output_subdirectory = str(
            config.get("output_subdirectory")
            or get_config().get("output_subdirectory")
            or "exports"
        ).strip()
        return FilesystemArtifactSink(
            base_dir,
            output_subdirectory=output_subdirectory,
        )
    if destination == "git":
        raw_repository_id = config.get("git_repository_id")
        if raw_repository_id in (None, ""):
            raise ValueError("store-artifact: git_repository_id is required when destination=git")
        repository = load_git_repository(
            require_repository_id(raw_repository_id, step_id="store-artifact")
        )
        return GitArtifactSink(
            repository,
            repository_subdirectory=str(
                config.get("repository_subdirectory")
                or get_config().get("repository_subdirectory")
                or ""
            ),
            pull_before_write=parse_bool_flag(config, "pull_before_write"),
            commit_after_write=parse_bool_flag(config, "commit_after_write"),
            push_after_write=parse_bool_flag(config, "push_after_write"),
        )
    raise ValueError(f"store-artifact: unsupported destination {destination!r}")


def _filename_template(config: dict[str, Any]) -> str:
    return str(
        config.get("filename_template")
        or get_config().get("filename_template")
        or "{device.name}_{run.timestamp}.cfg"
    ).strip()


def _commit_message_template(config: dict[str, Any]) -> str:
    return str(
        config.get("commit_message_template")
        or get_config().get("commit_message_template")
        or "commit {timestamp}"
    ).strip()


def _render_commit_message(config: dict[str, Any], context: WorkflowContext) -> str:
    return render_step_template(
        _commit_message_template(config),
        run_id=context.run_id,
        workflow_id=context.workflow_id,
    )


def _relative_export_path(
    *,
    device: DeviceContext,
    item: ExportableContent,
    config: dict[str, Any],
    index: int,
    run_id: str,
) -> str:
    template = _filename_template(config)
    extra = dict(item.extra)
    extra["index"] = index + 1
    return render_device_template(
        template,
        device,
        extra=extra,
        options=TemplateRenderOptions(
            strict=parse_strict_templates(config),
            run_id=run_id,
        ),
    )


def _step_error(exc: BaseException, *, node_id: str) -> DeviceError:
    """The error record for an exception of this step.

    A git error the app built itself keeps its text (scrubbed of URL credentials) and its
    ``FailureInfo``, so a rejected push still reads as one; anything else (a filesystem or
    template error) is reduced to its class name by ``device_error_from_exception``.
    """
    if isinstance(exc, GitOperationError):
        return DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code=type(exc).__name__.lower(),
            message=scrub_url_credentials(str(exc)),
            failure=failure_from_exception(exc) or classify_git_exception(exc),
        )
    return device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)


def _prepare_failure_outcomes(
    *, context: WorkflowContext, node_id: str, run_id: Any, error: GitSinkPrepareError
) -> list[StepOutcome]:
    cause = error.__cause__ if isinstance(error.__cause__, Exception) else error
    logger.error("store-artifact git prepare failed run_id=%s: %s", run_id, cause)
    record = _step_error(cause, node_id=node_id)
    return whole_step_failure(
        context,
        node_id=node_id,
        step_id=_STEP_ID,
        code=record.code,
        message=record.message,
        failure=record.failure,
    )


async def _store_for_device(
    *,
    device_id: str,
    device: DeviceContext,
    parsed: _ParsedStoreConfig,
    sink: ArtifactSink,
    config: dict[str, Any],
    context: WorkflowContext,
    artifact_service: ArtifactService,
    records: list[dict[str, Any]],
) -> DeviceContext | Fail:
    """One device. ``records`` collects what was written, also when a later item fails; an
    exception that escapes is turned into a failed device by the runner."""
    export_items = list_exportable_content(
        device,
        content_source=parsed.content_source,
        source_step_node_id=parsed.source_step_node_id,
        parsed_output_key=parsed.parsed_output_key,
        step_id=_STEP_ID,
    )
    if not export_items:
        return Fail(
            "missing_content",
            f"No {parsed.content_source!r} content available for device {device_id}. "
            "Ensure an upstream step produced the selected data.",
            _NO_CONTENT,
        )

    for index, item in enumerate(export_items):
        content = await artifact_service.resolve(item.artifact_ref)
        relative_path = _relative_export_path(
            device=device,
            item=item,
            config=config,
            index=index,
            run_id=context.run_id,
        )
        export: StoredExport = await sink.write_text(
            relative_path=relative_path,
            content=content,
            workflow_id=context.workflow_id,
            run_id=context.run_id,
        )
        records.append(
            {
                "device_id": device_id,
                "content_source": parsed.content_source,
                "kind": item.kind,
                "path": export.path,
                "destination": export.destination,
                "size_bytes": export.size_bytes,
                "sha256": export.sha256,
                **item.extra,
            }
        )
    return device.model_copy(update={"status": DeviceStatus.OK})


async def _finalize_git_sink(
    *,
    git_sink: GitArtifactSink | None,
    config: dict[str, Any],
    context: WorkflowContext,
    node_id: str,
    run_id: Any,
    metadata: dict[str, Any],
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> None:
    if git_sink is None or not git_sink.has_writes:
        return
    if not success_devices:
        # every device failed: nothing is committed, so put back what a failed device wrote
        await asyncio.shield(git_sink.discard_written())
        return
    try:
        # the sink re-checks the lease and puts the tree back when this fails (W8-03, W9-02)
        finalize_result = await git_sink.finalize(_render_commit_message(config, context))
        if finalize_result is not None:
            metadata[f"{node_id}.git_export"] = {
                "git_repository_id": git_sink.repository_ref,
                "committed": finalize_result.committed,
                "pushed": finalize_result.pushed,
                "commit_sha": finalize_result.commit_sha,
                "files_changed": finalize_result.files_changed,
                "message": finalize_result.message,
            }
    except Exception as exc:
        logger.error("store-artifact git finalize failed run_id=%s: %s", run_id, exc)
        record = _step_error(exc, node_id=node_id)
        for device_id in list(success_devices):
            failed_devices[device_id] = mark_device_failed(
                success_devices.pop(device_id),
                node_id=node_id,
                step_id=_STEP_ID,
                code=record.code,
                message=record.message,
                failure=record.failure,
            )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    parsed = _parse_store_config(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = get_db_session()
    try:
        base_dir = GeneralSettingsService(db).resolved_export_directory()
    finally:
        db.close()
    sink = _build_sink(config, base_dir=base_dir)
    git_sink = sink if isinstance(sink, GitArtifactSink) else None
    metadata = dict(context.metadata)

    logger.info(
        "store-artifact run_id=%s devices=%d source=%s destination=%s",
        log_run_id(run),
        len(context.devices),
        parsed.content_source,
        sink.destination,
    )

    # The sink's session holds the repository lock across prepare -> per-device writes ->
    # finalize: two concurrent callers (fan-out children, sibling branches, separate runs)
    # against one repository must not interleave their clone/pull/write/commit/push sequences.
    sink_session = git_sink.session() if git_sink is not None else contextlib.nullcontext()
    try:
        async with sink_session:
            records: dict[str, list[dict[str, Any]]] = {i: [] for i in context.devices}

            async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
                return await _store_for_device(
                    device_id=device_id,
                    device=device,
                    parsed=parsed,
                    sink=sink,
                    config=config,
                    context=context,
                    artifact_service=artifact_service,
                    records=records[device_id],
                )

            batch = await run_per_device(context, work, node_id=node_id, step_id=_STEP_ID)
            success_devices, failed_devices = dict(batch.ok), dict(batch.failed)
            # In context order, whatever order the devices finished in.
            all_stored = [row for rows in records.values() for row in rows]
            await _finalize_git_sink(
                git_sink=git_sink,
                config=config,
                context=context,
                node_id=node_id,
                run_id=log_run_id(run),
                metadata=metadata,
                success_devices=success_devices,
                failed_devices=failed_devices,
            )
    except GitSinkPrepareError as exc:
        return _prepare_failure_outcomes(
            context=context, node_id=node_id, run_id=log_run_id(run), error=exc
        )
    if all_stored:
        metadata[f"{node_id}.stored_artifacts"] = all_stored
    logger.info(
        "store-artifact wrote %d file(s) for %d/%d devices run_id=%s",
        len(all_stored),
        len(success_devices),
        len(context.devices),
        log_run_id(run),
    )
    return build_outcomes(context, success_devices, failed_devices, metadata=metadata)
