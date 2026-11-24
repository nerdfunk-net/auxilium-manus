"""Executor for the open-change-request step.

Ends a *stage run*: commits the rendered configs produced upstream to a
per-change git branch (``manus/cr-{run.id}``), pushes it, stores a unified-diff
artifact, and records a ``ChangeRequest`` row in ``status="staged"``. A reviewer
(UI or a signed git webhook) approves it later, which dispatches a separate
deploy run. See ``doc/CICD_PIPELINE.md``.

Concurrent callers against the same repository — separate stage runs, fan-out
children, or independent sibling branches in one run — are serialised by a
per-repo Redis lock (``services/git/repo_lock.py``), so the working tree
itself is never corrupted. That lock doesn't make the step fan-out/branch-safe
in the useful sense, though: each caller still opens its own branch/commit/
change request. Place it after any Fan In node (or other join point) so
exactly one change request comes out, not one per fan-out child or sibling
branch.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.git.failure import classify_git_exception
from services.git.paths import write_text_within_repo
from services.git.repo_lock import git_repo_lock
from services.git.scrub import scrub_url_credentials
from services.git.tree_scope import git_branch_scope
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    parse_strict_templates,
    render_device_template,
    render_step_template,
    sanitize_relative_path,
)
from workflow_steps.common.content_resolver import list_exportable_content, parse_content_source
from workflow_steps.common.device_outcomes import whole_step_failure
from workflow_steps.common.duplicate_keys import find_duplicate_keys
from workflow_steps.common.git_repository_loader import load_git_repository, parse_repository_id
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_int_flag
from workflow_steps.open_change_request.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "open-change-request"
_DIFF_MAX_BYTES = 2 * 1024 * 1024
_DIFF_DEVICE_ID = "__change_request__"
_DEFAULT_EXPIRY_HOURS = 168


def _config_value(config: dict[str, Any], key: str) -> Any:
    value = config.get(key)
    if value in (None, ""):
        return get_config().get(key)
    return value


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _parse_expiry_hours(config: dict[str, Any]) -> int:
    """Hours until an un-actioned change request expires; ``0`` disables expiry (registry)."""
    return parse_int_flag(
        config, "expires_after_hours", default=_DEFAULT_EXPIRY_HOURS, minimum=0, step_id=_STEP_ID
    )


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
) -> list[tuple[str, str, Any]]:
    """Return (device_id, relative_path, artifact_ref) triples for every rendered
    file across all devices. Raises ValueError if nothing upstream produced
    content.
    """
    content_source = parse_content_source(config, step_id=_STEP_ID)
    source_step_node_id = str(config.get("source_step_node_id") or "").strip() or None
    parsed_output_key = str(config.get("parsed_output_key") or "").strip() or None
    filename_template = str(_config_value(config, "filename_template"))
    strict = parse_strict_templates(config)
    repo_subdir = str(_config_value(config, "repository_subdirectory") or "").strip("/\\")

    triples: list[tuple[str, str, Any]] = []
    for device_id, device in context.devices.items():
        if content_source == "rendered_template" and source_step_node_id is None:
            items = _all_rendered_templates(device, parsed_output_key)
        else:
            items = list_exportable_content(
                device,
                content_source=content_source,
                source_step_node_id=source_step_node_id,
                parsed_output_key=parsed_output_key,
                step_id=_STEP_ID,
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
            triples.append((device_id, rel, item.artifact_ref))

    if not triples:
        raise ValueError(
            f"{_STEP_ID}: no {content_source!r} content found upstream. "
            "Add a render-jinja-template step before this one."
        )
    duplicates = find_duplicate_keys(
        (f"{device_id}#{index}", rel) for index, (device_id, rel, _) in enumerate(triples)
    )
    if duplicates:
        colliding = sorted({triples[int(key.rsplit("#", 1)[1])][1] for key in duplicates})[:5]
        raise ValueError(
            f"{_STEP_ID}: more than one rendered file maps to the same repository path "
            f"({', '.join(colliding)}); select one source step, or add {{parsed.output_key}} or "
            "{{command.index}} to the filename template"
        )
    return triples


def _device_snapshot(
    context: WorkflowContext, device_paths: dict[str, str]
) -> list[dict[str, Any]]:
    """Slim per-device identity + committed config path, stored on the change
    request so the from-change-request step can rebuild the deploy inventory.
    """
    snapshot: list[dict[str, Any]] = []
    for device_id, device in context.devices.items():
        snapshot.append(
            {
                "id": device_id,
                "name": device.name,
                "hostname": device.hostname,
                "platform": device.platform,
                "network_driver": device.network_driver,
                "primary_ip4": device.primary_ip4,
                "config_path": device_paths.get(device_id),
            }
        )
    return snapshot


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
    with git_repo_lock(repository_id if repository_id is not None else -1) as lease:
        repo = git_service.open_or_clone(repository)
        base_ref = str(repository.get("branch") or "main")
        # The documented stage shape has no git-pull step: fetch, and branch from the fetched
        # origin rather than a possibly stale local branch.
        fetch_result = git_service.fetch(repository, repo=repo)
        if not fetch_result.success:
            raise fetch_result.error()
        # The branch scope restores the configured branch afterwards, so a later backup commit
        # on the shared tree does not land on the change-request branch (C5-01).
        with git_branch_scope(git_service, repo, repository, branch, f"origin/{base_ref}"):
            repo_root: Path = git_service.get_repo_path(repository)
            written: list[str] = []
            for rel_path, content in files:
                safe_rel = sanitize_relative_path(rel_path)
                write_text_within_repo(repo_root, safe_rel, content)
                if safe_rel not in written:
                    written.append(safe_rel)

            commit_result = git_service.commit(
                repository, message=commit_message, files=written, repo=repo
            )
            if not commit_result.success:
                raise commit_result.error()
            if not commit_result.commit_sha:
                raise NothingToReview()

            lease.ensure_held()
            push_result = git_service.push(repository, repo=repo, branch=branch, force=True)
            if not push_result.success:
                raise push_result.error()

            raw_diff = git_service.diff_refs(repo, f"origin/{base_ref}", branch)

    return {
        "base_ref": base_ref,
        "commit_sha": commit_result.commit_sha,
        "files_changed": commit_result.files_changed,
        "diff": raw_diff,
    }


class NothingToReview(Exception):  # noqa: N818 - a signal, not an error
    """The rendered files equal the base branch: no change request is needed."""


def _unchanged_outcomes(*, context: WorkflowContext, node_id: str) -> list[StepOutcome]:
    metadata = {
        **context.metadata,
        f"{node_id}.change_request": {"success": True, "unchanged": True},
    }
    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": {}, "metadata": metadata}),
        ),
        StepOutcome(
            name="unchanged",
            context=context.model_copy(update={"metadata": metadata}),
            summary="rendered configs equal the base branch; no change request opened",
        ),
    ]


# A setup problem (repository id, expiry, no devices, a conflicting change request).
_BAD_CONFIG = FailureInfo(phase="config", kind="bad_request", hint="check_request")


def _change_request_failure(
    *,
    context: WorkflowContext,
    node_id: str,
    message: str,
    failure: FailureInfo | None = _BAD_CONFIG,
) -> list[StepOutcome]:
    """Every device fails with the same error; the message is scrubbed of URL credentials."""
    message = scrub_url_credentials(message)
    return whole_step_failure(
        context,
        node_id=node_id,
        step_id=_STEP_ID,
        code="change_request_failed",
        message=message,
        failure=failure,
        metadata={f"{node_id}.change_request": {"success": False, "message": message}},
    )


@dataclass(frozen=True)
class _Naming:
    branch: str
    commit_message: str
    title: str


def _render_naming(config: dict[str, Any], *, run: WorkflowRun, workflow_id: str) -> _Naming:
    # Templates use the integer WorkflowRun.id ({run.id} → 42) so the branch is
    # short and human-correlatable; artifact storage still keys off the run uuid.
    template_run_id = str(run.id)

    def render(key: str) -> str:
        return render_step_template(
            str(_config_value(config, key)), run_id=template_run_id, workflow_id=workflow_id
        )

    return _Naming(
        branch=render("branch_template"),
        commit_message=render("commit_message_template"),
        title=render("title_template"),
    )


def _create_change_request(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    repository_id: int,
    staged: dict[str, Any],
    naming: _Naming,
    device_paths: dict[str, str],
    diff_ref: Any,
    diff_stats: dict[str, Any],
) -> Any:
    """Persist the staged change as a ``ChangeRequest`` row (may raise ``ConflictError``)."""
    from services.change_requests.change_request_service import ChangeRequestService

    device_ids = list(run.device_ids or list(context.devices.keys()))
    devices_snapshot = _device_snapshot(context, device_paths)
    db = get_db_session()
    try:
        return ChangeRequestService(db).create_from_step(
            source_workflow_id=_as_int(context.workflow_id),
            source_run_id=_as_int(run.id),
            deploy_workflow_id=_as_int(config.get("deploy_workflow_id")),
            git_repository_id=repository_id,
            base_branch=staged["base_ref"],
            branch=naming.branch,
            commit_sha=staged["commit_sha"],
            title=naming.title,
            device_ids=device_ids,
            devices=devices_snapshot,
            run_inputs=dict(run.run_inputs or {}),
            diff_artifact_id=diff_ref.artifact_id,
            diff_stats=diff_stats,
            expires_after_hours=_parse_expiry_hours(config),
        )
    finally:
        db.close()


async def _stage(
    git_service: Any,
    repository: dict[str, Any],
    *,
    naming: _Naming,
    files: list[tuple[str, str]],
    run: WorkflowRun,
    repository_id: int,
) -> dict[str, Any]:
    """Commit + push the rendered files to the per-change branch (blocking git in a thread)."""
    try:
        return await asyncio.to_thread(
            _stage_to_git,
            git_service,
            repository,
            branch=naming.branch,
            commit_message=naming.commit_message,
            files=files,
        )
    except Exception as exc:
        logger.error(
            "%s git staging failed run_id=%s repository_id=%s: %s",
            _STEP_ID,
            log_run_id(run),
            repository_id,
            exc,
        )
        raise


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

    try:
        repository_id = parse_repository_id(config.get("git_repository_id"), step_id=_STEP_ID)
    except ValueError as exc:
        return _change_request_failure(context=context, node_id=node_id, message=str(exc))
    if repository_id is None:
        return _change_request_failure(
            context=context,
            node_id=node_id,
            message=f"{_STEP_ID}: git_repository_id is not configured",
        )
    try:
        _parse_expiry_hours(config)  # a typo fails here, before anything is pushed
    except ValueError as exc:
        return _change_request_failure(context=context, node_id=node_id, message=str(exc))
    if not context.devices:
        # An empty branch is a no-op (D2): nothing to review, nothing staged, nothing pushed.
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "%s started run_id=%s repository_id=%s devices=%d",
        _STEP_ID,
        log_run_id(run),
        repository_id,
        len(context.devices),
    )

    try:
        repository = load_git_repository(repository_id)
        rendered = _collect_rendered_files(config=config, context=context)
    except ValueError as exc:
        return _change_request_failure(context=context, node_id=node_id, message=str(exc))

    resolved_files: list[tuple[str, str]] = []
    device_paths: dict[str, str] = {}
    for device_id, rel_path, artifact_ref in rendered:
        resolved_files.append((rel_path, await artifact_service.resolve(artifact_ref)))
        device_paths.setdefault(device_id, rel_path)

    naming = _render_naming(config, run=run, workflow_id=context.workflow_id)

    import service_factory

    git_service = service_factory.build_git_service()

    try:
        staged = await _stage(
            git_service,
            repository,
            naming=naming,
            files=resolved_files,
            run=run,
            repository_id=repository_id,
        )
    except NothingToReview:
        return _unchanged_outcomes(context=context, node_id=node_id)
    except Exception as exc:  # noqa: BLE001 — surfaced as a step failure outcome
        return _change_request_failure(
            context=context,
            node_id=node_id,
            message=str(exc),
            failure=failure_from_exception(exc) or classify_git_exception(exc),
        )

    diff_text, truncated = _truncate_diff(staged["diff"])
    diff_ref = await artifact_service.store(
        content=diff_text,
        kind="comparison_diff",
        device_id=_DIFF_DEVICE_ID,
        run_id=context.run_id,
        media_type="text/plain",
    )
    diff_stats = {**_diff_stats(diff_text), "truncated": truncated}

    from core.domain_exceptions import ConflictError

    try:
        change_request = _create_change_request(
            config=config,
            context=context,
            run=run,
            repository_id=repository_id,
            staged=staged,
            naming=naming,
            device_paths=device_paths,
            diff_ref=diff_ref,
            diff_stats=diff_stats,
        )
    except ConflictError as exc:
        return _change_request_failure(context=context, node_id=node_id, message=str(exc))

    metadata = {
        **context.metadata,
        f"{node_id}.change_request": {
            "success": True,
            "change_request_id": change_request.id,
            "uuid": change_request.uuid,
            "branch": naming.branch,
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
        naming.branch,
        str(staged["commit_sha"])[:8],
        log_run_id(run),
    )
    return [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"metadata": metadata}),
        )
    ]
