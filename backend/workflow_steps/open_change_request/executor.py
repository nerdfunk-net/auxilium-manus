"""Executor for the open-change-request step.

Ends a *stage run*: commits the rendered configs produced upstream to a
per-change git branch (``manus/cr-{run.id}``), pushes it, stores a unified-diff
artifact, and records a ``ChangeRequest`` row in ``status="staged"``. A reviewer
(UI or a signed git webhook) approves it later, which dispatches a separate
deploy run. See ``doc/CICD_PIPELINE.md``.

Not fan-out-safe — it branches and commits against a shared working tree. Place
it after any Fan In node, never inside a fan-out branch. Concurrent stage runs
against the same repository are serialised by a per-repo Redis lock.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.change_requests.repo_lock import repo_stage_lock
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    parse_strict_templates,
    render_device_template,
    render_step_template,
    sanitize_relative_path,
)
from workflow_steps.common.content_resolver import list_exportable_content, parse_content_source
from workflow_steps.common.git_repository_loader import load_git_repository
from workflow_steps.open_change_request.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "open-change-request"
_DIFF_MAX_BYTES = 2 * 1024 * 1024
_DIFF_DEVICE_ID = "__change_request__"


def _config_value(config: dict[str, Any], key: str) -> Any:
    value = config.get(key)
    if value in (None, ""):
        return get_config().get(key)
    return value


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truncate_diff(diff_text: str) -> tuple[str, bool]:
    encoded = diff_text.encode("utf-8")
    if len(encoded) <= _DIFF_MAX_BYTES:
        return diff_text, False
    clipped = encoded[:_DIFF_MAX_BYTES].decode("utf-8", errors="ignore")
    return clipped + "\n... [diff truncated]\n", True


def _diff_stats(diff_text: str) -> dict[str, int | bool]:
    additions = 0
    deletions = 0
    files = 0
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            files += 1
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {"additions": additions, "deletions": deletions, "files": files}


def _all_rendered_templates(device: Any, parsed_output_key: str | None) -> list[Any]:
    """Every rendered-template artifact on a device, regardless of which
    render-jinja-template step produced it. Used when ``source_step_node_id`` is
    not set — committing all rendered configs to the review branch is a safe
    default (unlike deploy-rendered-template, which must target one step).
    """
    from models.workflow_context import ArtifactRef
    from workflow_steps.common.content_resolver import ExportableContent

    entries = (
        [(parsed_output_key, device.parsed.get(parsed_output_key))]
        if parsed_output_key
        else list(device.parsed.items())
    )
    items: list[Any] = []
    for key, raw in entries:
        if not isinstance(raw, dict):
            continue
        artifact_raw = raw.get("artifact_ref")
        if not (isinstance(artifact_raw, dict) and artifact_raw.get("artifact_id")):
            continue
        if raw.get("kind") not in (None, "rendered_template"):
            continue
        if not raw.get("step_node_id"):
            continue
        ref = ArtifactRef.model_validate(artifact_raw)
        items.append(
            ExportableContent(
                kind="rendered_template",
                media_type=ref.media_type,
                artifact_ref=ref,
                extra={
                    "content_source": "rendered_template",
                    "output_key": str(raw.get("output_key") or key),
                    "source_step_node_id": str(raw.get("step_node_id") or ""),
                },
            )
        )
    return items


def _collect_rendered_files(
    *, config: dict[str, Any], context: WorkflowContext
) -> list[tuple[str, Any]]:
    """Return (relative_path, artifact_ref) pairs for every rendered file across
    all devices. Raises ValueError if nothing upstream produced content.
    """
    content_source = parse_content_source(config)
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None
    filename_template = str(_config_value(config, "filename_template"))
    strict = parse_strict_templates(config)
    repo_subdir = str(_config_value(config, "repository_subdirectory") or "").strip("/\\")

    pairs: list[tuple[str, Any]] = []
    for device in context.devices.values():
        if content_source == "rendered_template" and source_step_node_id is None:
            items = _all_rendered_templates(device, parsed_output_key)
        else:
            items = list_exportable_content(
                device,
                content_source=content_source,
                source_step_node_id=source_step_node_id,
                parsed_output_key=parsed_output_key,
            )
        for index, item in enumerate(items):
            extra = dict(item.extra)
            extra["index"] = index + 1
            rel = render_device_template(
                filename_template,
                device,
                extra=extra,
                options=TemplateRenderOptions(strict=strict, run_id=context.run_id),
            )
            if repo_subdir:
                rel = sanitize_relative_path(f"{repo_subdir}/{rel}")
            pairs.append((rel, item.artifact_ref))

    if not pairs:
        raise ValueError(
            f"{_STEP_ID}: no {content_source!r} content found upstream. "
            "Add a render-jinja-template step before this one."
        )
    return pairs


def _stage_to_git(
    git_service: Any,
    repository: dict[str, Any],
    *,
    branch: str,
    commit_message: str,
    files: list[tuple[str, str]],
) -> dict[str, Any]:
    """Branch, write files, commit, push, diff — all synchronous git work,
    run inside a per-repo advisory lock. Raises RuntimeError on any git failure.
    """
    repository_id = _as_int(repository.get("id"))
    with repo_stage_lock(repository_id if repository_id is not None else -1):
        repo = git_service.open_or_clone(repository)
        base_ref = str(repository.get("branch") or "main")
        git_service.checkout_new_branch(repo, branch, base_ref)

        repo_root: Path = git_service.get_repo_path(repository)
        written: list[str] = []
        for rel_path, content in files:
            safe_rel = sanitize_relative_path(rel_path)
            target = repo_root / safe_rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            if safe_rel not in written:
                written.append(safe_rel)

        commit_result = git_service.commit(
            repository, message=commit_message, files=written, repo=repo
        )
        if not commit_result.success:
            raise RuntimeError(commit_result.message)
        if not commit_result.commit_sha:
            raise RuntimeError(
                "Rendered configs are identical to the base branch — nothing to review"
            )

        push_result = git_service.push(repository, repo=repo, branch=branch, force=True)
        if not push_result.success:
            raise RuntimeError(push_result.message)

        raw_diff = git_service.diff_refs(repo, base_ref, branch)

    return {
        "base_ref": base_ref,
        "commit_sha": commit_result.commit_sha,
        "files_changed": commit_result.files_changed,
        "diff": raw_diff,
    }


def _failure_outcomes(
    *, context: WorkflowContext, node_id: str, message: str
) -> list[StepOutcome]:
    metadata = {
        **context.metadata,
        f"{node_id}.change_request": {"success": False, "message": message},
    }
    failed_devices = {
        device_id: device.model_copy(
            update={
                "status": DeviceStatus.FAILED,
                "errors": [
                    *device.errors,
                    DeviceError(
                        node_id=node_id,
                        step_id=_STEP_ID,
                        code="change_request_failed",
                        message=message,
                    ),
                ],
            }
        )
        for device_id, device in context.devices.items()
    }
    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": {}, "metadata": metadata}),
        ),
        StepOutcome(
            name="failure",
            context=context.model_copy(
                update={"devices": failed_devices, "metadata": metadata}
            ),
        ),
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
    del device_sessions

    repository_id = _as_int(config.get("git_repository_id"))
    if repository_id is None:
        return _failure_outcomes(
            context=context,
            node_id=node_id,
            message=f"{_STEP_ID}: git_repository_id is not configured",
        )
    if not context.devices:
        return _failure_outcomes(
            context=context,
            node_id=node_id,
            message=f"{_STEP_ID}: no devices in the input context",
        )

    logger.info(
        "%s started run_id=%s repository_id=%s devices=%d",
        _STEP_ID,
        run.id,
        repository_id,
        len(context.devices),
    )

    try:
        repository = load_git_repository(repository_id)
        rendered = _collect_rendered_files(config=config, context=context)
    except ValueError as exc:
        return _failure_outcomes(context=context, node_id=node_id, message=str(exc))

    resolved_files: list[tuple[str, str]] = []
    for rel_path, artifact_ref in rendered:
        resolved_files.append((rel_path, await artifact_service.resolve(artifact_ref)))

    # Templates use the integer WorkflowRun.id ({run.id} → 42) so the branch is
    # short and human-correlatable; artifact storage still keys off the run uuid.
    template_run_id = str(run.id)
    branch = render_step_template(
        str(_config_value(config, "branch_template")),
        run_id=template_run_id,
        workflow_id=context.workflow_id,
    )
    commit_message = render_step_template(
        str(_config_value(config, "commit_message_template")),
        run_id=template_run_id,
        workflow_id=context.workflow_id,
    )
    title = render_step_template(
        str(_config_value(config, "title_template")),
        run_id=template_run_id,
        workflow_id=context.workflow_id,
    )

    import service_factory

    git_service = service_factory.build_git_service()

    try:
        staged = await asyncio.to_thread(
            _stage_to_git,
            git_service,
            repository,
            branch=branch,
            commit_message=commit_message,
            files=resolved_files,
        )
    except Exception as exc:  # noqa: BLE001 — surfaced as a step failure outcome
        logger.error(
            "%s git staging failed run_id=%s repository_id=%s: %s",
            _STEP_ID,
            run.id,
            repository_id,
            exc,
        )
        return _failure_outcomes(context=context, node_id=node_id, message=str(exc))

    diff_text, truncated = _truncate_diff(staged["diff"])
    diff_ref = await artifact_service.store(
        content=diff_text,
        kind="comparison_diff",
        device_id=_DIFF_DEVICE_ID,
        run_id=context.run_id,
        media_type="text/plain",
    )
    diff_stats = {**_diff_stats(diff_text), "truncated": truncated}

    device_ids = list(run.device_ids or list(context.devices.keys()))
    db = get_db_session()
    try:
        from core.domain_exceptions import ConflictError
        from services.change_requests.change_request_service import ChangeRequestService

        try:
            change_request = ChangeRequestService(db).create_from_step(
                source_workflow_id=_as_int(context.workflow_id),
                source_run_id=_as_int(run.id),
                deploy_workflow_id=_as_int(config.get("deploy_workflow_id")),
                git_repository_id=repository_id,
                base_branch=staged["base_ref"],
                branch=branch,
                commit_sha=staged["commit_sha"],
                title=title,
                device_ids=device_ids,
                run_inputs=dict(run.run_inputs or {}),
                diff_artifact_id=diff_ref.artifact_id,
                diff_stats=diff_stats,
                expires_after_hours=int(_config_value(config, "expires_after_hours") or 168),
            )
        except ConflictError as exc:
            return _failure_outcomes(context=context, node_id=node_id, message=str(exc))
    finally:
        db.close()

    metadata = {
        **context.metadata,
        f"{node_id}.change_request": {
            "success": True,
            "change_request_id": change_request.id,
            "uuid": change_request.uuid,
            "branch": branch,
            "commit_sha": staged["commit_sha"],
            "status": "staged",
            "diff_artifact_id": diff_ref.artifact_id,
            "diff_stats": diff_stats,
        },
    }

    logger.info(
        "%s created change_request_id=%s branch=%s commit=%s run_id=%s",
        _STEP_ID,
        change_request.id,
        branch,
        str(staged["commit_sha"])[:8],
        run.id,
    )
    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
        )
    ]
