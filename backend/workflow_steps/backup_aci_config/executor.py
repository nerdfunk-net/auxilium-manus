"""Executor for the backup-aci-config step: ACI tenant and access-policy configuration into git.

One JSON file per tenant plus one for the access policies, written into a ``GitRepository`` and
committed (optionally pushed). Everything is read from the APIC *before* the repository is touched:
if any object cannot be read the step fails and writes nothing, so a backup never silently keeps an
older version of a file. Files of tenants that no longer exist are reported (``stale_files``), not
deleted. The workflow's devices are not used and pass through unchanged.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from git.exc import GitCommandError

import service_factory
from core.models.runs import WorkflowRun
from models.failure import failure_from_exception
from models.workflow_context import StepOutcome, WorkflowContext
from services.aci.common.exceptions import AciAPIError, AciAuthError, AciValidationError
from services.artifacts import ArtifactService
from services.artifacts.sinks.git_sink import GitArtifactSink, GitSinkPrepareError
from services.git.failure import GitOperationError, classify_git_exception
from services.git.scrub import scrub_url_credentials
from workflow_steps.common.controller_failure import controller_failure_outcomes
from workflow_steps.common.controller_sources import ACI
from workflow_steps.common.fact_entries import parse_output_key_config
from workflow_steps.common.failure_records import INVALID_RESPONSE
from workflow_steps.common.git_repository_loader import load_git_repository, parse_repository_id
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

STEP_ID = "backup-aci-config"
DEFAULT_SUBDIRECTORY = "aci"
DEFAULT_MESSAGE = "ACI configuration backup of {source_id}"
DEFAULT_OUTPUT_KEY = "aci_backup"
TENANT_DIR = "tenants"
MAX_MESSAGE_CHARS = 200
MAX_SUMMARY_CHARS = 500
# A git error ends the step on ``failure``; anything else (a filesystem error, a bug) raises.
_GIT_ERRORS = (GitOperationError, GitCommandError)
_TENANT_NAME = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")


def _build_sink(
    repository: dict[str, Any], subdirectory: str, *, commit: bool, push: bool
) -> GitArtifactSink:
    return GitArtifactSink(
        repository,
        repository_subdirectory=subdirectory,
        pull_before_write=True,
        commit_after_write=commit,
        push_after_write=push,
    )


def _repository_id(config: dict[str, Any]) -> int:
    value = parse_repository_id(config.get("git_repository_id"), step_id=STEP_ID)
    if value is None:
        raise ValueError(f"{STEP_ID}: git_repository_id is not configured")
    if value < 1:
        raise ValueError(f"{STEP_ID}: git_repository_id must be a whole number")
    return value


def _subdirectory(config: dict[str, Any]) -> str:
    raw = config.get("repository_subdirectory")
    value = DEFAULT_SUBDIRECTORY if raw is None else str(raw).strip()
    if value.startswith(("/", "\\")) or ".." in value.replace("\\", "/").split("/"):
        raise ValueError(f"{STEP_ID}: repository_subdirectory must stay inside the repository")
    return value.strip("/\\")


def _tenants(raw: Any) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{STEP_ID}: tenants must be a list of tenant names")
    names = [item.strip() for item in raw if item.strip()]
    bad = [name for name in names if not _TENANT_NAME.match(name)]
    if bad:
        raise ValueError(f"{STEP_ID}: not a tenant name: {', '.join(repr(b) for b in bad)}")
    return tuple(names) or None


def _message(config: dict[str, Any], source_id: str) -> str:
    raw = config.get("commit_message")
    template = DEFAULT_MESSAGE if raw is None else str(raw).strip()
    if not template or len(template) > MAX_MESSAGE_CHARS:
        raise ValueError(f"{STEP_ID}: commit_message must be 1 to {MAX_MESSAGE_CHARS} characters")
    return template.replace("{source_id}", source_id)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # no device is contacted

    source_id = str(config.get("aci_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{STEP_ID}: aci_source_id is not configured")
    repository_id = _repository_id(config)
    subdirectory = _subdirectory(config)
    tenants = _tenants(config.get("tenants"))
    include_access_policies = parse_bool_flag(config, "include_access_policies", default=True)
    commit = parse_bool_flag(config, "commit", default=True)
    push = parse_bool_flag(config, "push", default=False)
    if push and not commit:
        raise ValueError(f"{STEP_ID}: push needs commit")
    message = _message(config, source_id)
    output_key = parse_output_key_config(
        config.get("output_key"),
        step_id=STEP_ID,
        default=DEFAULT_OUTPUT_KEY,
        key_name="output_key",
    )

    db = require_session(run, STEP_ID)
    credentials = ACI.resolve_credentials(db, source_id, step_id=STEP_ID)
    repository = load_git_repository(repository_id)

    logger.info("%s started run_id=%s node_id=%s", STEP_ID, context.run_id, node_id)
    service = service_factory.build_aci_config_export_service(credentials)
    try:
        export = await service.export(
            tenants=tenants, include_access_policies=include_access_policies
        )
    except AciValidationError as exc:
        raise ValueError(f"{STEP_ID}: {exc}") from exc
    except (AciAPIError, AciAuthError) as exc:
        return controller_failure_outcomes(
            context, exc, label="APIC", step_id=STEP_ID, logger=logger
        )
    if export.errors:
        # The object paths say what to look at; the APIC's reasons are not carried along.
        paths = ", ".join(sorted(export.errors))
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=(
                    f"{len(export.errors)} object(s) could not be read, nothing was written "
                    f"({paths})"
                ),
                failure=INVALID_RESPONSE,
            )
        ]

    sink = _build_sink(repository, subdirectory, commit=commit, push=push)
    try:
        stale, result = await _write_export(sink, export.files, context, message, tenants=tenants)
    except GitSinkPrepareError as exc:
        if not isinstance(exc.__cause__, _GIT_ERRORS):
            raise
        return _git_failure_outcomes(context, exc.__cause__)
    except _GIT_ERRORS as exc:
        return _git_failure_outcomes(context, exc)

    entry: dict[str, Any] = {
        "git_repository_id": sink.repository_ref,
        "tenants": list(export.tenants),
        "files": sorted(export.files),
        "stale_files": stale,
        "committed": bool(result and result.committed),
        "pushed": bool(result and result.pushed),
        "commit_sha": result.commit_sha if result else None,
        "files_changed": result.files_changed if result else 0,
        "message": result.message if result else "No git commit or push performed",
    }
    logger.info(
        "%s finished run_id=%s files=%d changed=%d stale=%d",
        STEP_ID,
        context.run_id,
        len(export.files),
        entry["files_changed"],
        len(stale),
    )
    new_context = context.model_copy(
        update={"metadata": {**context.metadata, f"{node_id}.{output_key}": entry}}
    )
    text = f"{len(export.files)} file(s), {entry['files_changed']} changed"
    outcomes = [StepOutcome(name="success", context=new_context, summary=text)]
    if entry["files_changed"] > 0:
        outcomes.append(StepOutcome(name="changed", context=new_context, summary=text))
    return outcomes


async def _write_export(
    sink: GitArtifactSink,
    files: dict[str, str],
    context: WorkflowContext,
    message: str,
    *,
    tenants: tuple[str, ...] | None,
) -> tuple[list[str], Any]:
    """Write, list the stale files and finalize, inside the sink's session.

    The session holds the repository lock from prepare to finalize, puts a half-written tree
    back on any failure and re-checks the lease before the commit.
    """
    async with sink.session():
        for path, content in sorted(files.items()):
            await sink.write_text(
                relative_path=path,
                content=content,
                workflow_id=context.workflow_id,
                run_id=context.run_id,
            )
        stale = [] if tenants else _stale_files(sink, files)
        return stale, await sink.finalize(message)


def _git_failure_outcomes(context: WorkflowContext, exc: BaseException) -> list[StepOutcome]:
    """``[failure]`` for a git error: context unchanged, the scrubbed git message, the record."""
    text = scrub_url_credentials(str(exc))
    logger.warning(
        "%s git failed (%s) run_id=%s: %s", STEP_ID, type(exc).__name__, context.run_id, text
    )
    summary = f"git failed: {text}"
    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[: MAX_SUMMARY_CHARS - 1] + "…"
    return [
        StepOutcome(
            name="failure",
            context=context,
            summary=summary,
            failure=failure_from_exception(exc) or classify_git_exception(exc),
        )
    ]


def _stale_files(sink: GitArtifactSink, written: dict[str, str]) -> list[str]:
    """Tenant files in the repository folder whose tenant the APIC no longer has."""
    return sorted(
        f"{TENANT_DIR}/{name}"
        for name in sink.existing_files(TENANT_DIR)
        if name.endswith(".json") and f"{TENANT_DIR}/{name}" not in written
    )
