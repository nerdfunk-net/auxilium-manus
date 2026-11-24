"""Executor for the get-age-of-backup step.

Reads when a device's config backup in a git repository last changed (the newest commit that
touched its file) and, optionally, when a "backup checked" marker for the device was last stored
by a Store in DB step. The ages are written as whole days into a separate attribute bag.

A repository records a commit only when the file's content changed, so the commit date alone says
"last changed", not "last backed up"; the marker (``device_data_records.updated_at``) says "last
checked".
"""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceStatus, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.device_data.device_data_service import DeviceDataService
from services.execution.run_events_reporter import current_run_event_context, emit_run_event
from services.git import safe_read
from services.git.commit_info import LastCommit, last_commit_of
from services.workflow_context.attribute_path import DEVICE_SCALAR_FIELDS
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    TemplateResolutionError,
    render_device_template,
)
from workflow_steps.common.attribute_write import RESERVED_BAG_NAMES, set_device_attribute
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.file_source_root import resolve_git_root
from workflow_steps.common.git_repository_loader import parse_repository_id
from workflow_steps.common.placeholder_template import render_placeholder_template
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-age-of-backup"
_DEFAULT_BAG = "backup_age"
_BAG_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECONDS_PER_DAY = 86400
_MAX_NAMED_DEVICES = 5

_GIT_NOT_FOUND = FailureInfo(phase="git", kind="not_found")
_GIT_BAD_REQUEST = FailureInfo(phase="git", kind="bad_request")
_RENDER_UNDEFINED = FailureInfo(phase="render", kind="undefined_variable")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _Parsed:
    git_repository_id: int
    path_template: str
    allow_stale: bool
    output_bag: str
    use_marker: bool
    marker_storage_key: str


@dataclass(frozen=True)
class _Backup:
    commit: LastCommit


class _DeviceProblem(Exception):
    """A per-device failure with a stable code and a closed-vocabulary cause."""

    def __init__(self, code: str, message: str, failure: FailureInfo) -> None:
        super().__init__(message)
        self.code = code
        self.failure = failure


def _parse(config: dict[str, Any]) -> _Parsed:
    git_repository_id = parse_repository_id(config.get("git_repository_id"), step_id=_STEP_ID)
    if git_repository_id is None:
        raise ValueError(f"{_STEP_ID}: git_repository_id is required")

    path_template = str(config.get("path_template") or "").strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    output_bag = str(config.get("output_bag") or _DEFAULT_BAG).strip()
    if not _BAG_NAME.match(output_bag):
        raise ValueError(f"{_STEP_ID}: output_bag must be letters, digits and underscores")
    if output_bag in RESERVED_BAG_NAMES or output_bag in DEVICE_SCALAR_FIELDS:
        raise ValueError(f"{_STEP_ID}: output_bag {output_bag!r} is reserved; choose another name")

    use_marker = parse_bool_flag(config, "use_marker")
    marker_storage_key = str(config.get("marker_storage_key") or "").strip()
    if use_marker and not marker_storage_key:
        raise ValueError(f"{_STEP_ID}: marker_storage_key is required when use_marker is on")

    return _Parsed(
        git_repository_id=git_repository_id,
        path_template=path_template,
        allow_stale=parse_bool_flag(config, "allow_stale_repository"),
        output_bag=output_bag,
        use_marker=use_marker,
        marker_storage_key=marker_storage_key,
    )


def _locate_backup(root: Path, device: DeviceContext, parsed: _Parsed, run_id: str) -> _Backup:
    """The newest commit of the device's backup file. Blocking (git); raises ``_DeviceProblem``."""
    try:
        relative = render_device_template(
            parsed.path_template,
            device,
            options=TemplateRenderOptions(strict=True, run_id=run_id),
        )
    except TemplateResolutionError as exc:
        raise _DeviceProblem("template_unresolved", str(exc), _RENDER_UNDEFINED) from exc
    except ValueError as exc:  # the path sanitiser: parent segments, absolute path, ...
        raise _DeviceProblem("unsafe_path", str(exc), _GIT_BAD_REQUEST) from exc

    try:
        target = safe_read.contain(root, relative)
    except safe_read.SafeReadError as exc:
        raise _DeviceProblem(
            "unsafe_path",
            f"the backup path {relative!r} is not allowed ({exc.code})",
            _GIT_BAD_REQUEST,
        ) from exc
    if not target.is_file():
        raise _DeviceProblem("backup_not_found", f"no backup file at {relative!r}", _GIT_NOT_FOUND)

    commit = last_commit_of(root, relative)
    if commit is None:
        raise _DeviceProblem(
            "no_backup_commit",
            f"the backup file {relative!r} has no commit in the repository",
            _GIT_NOT_FOUND,
        )
    return _Backup(commit=commit)


def _whole_days(since: datetime, now: datetime) -> int:
    return max(0, int((now - since).total_seconds() // _SECONDS_PER_DAY))


def _as_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _with_ages(
    device: DeviceContext,
    *,
    parsed: _Parsed,
    backup: _Backup,
    marker_time: datetime | None,
    now: datetime,
) -> DeviceContext:
    values: dict[str, Any] = {
        "last_changed": backup.commit.committed_at.isoformat(),
        "age_days": _whole_days(backup.commit.committed_at, now),
        "commit_sha": backup.commit.sha,
    }
    if parsed.use_marker:
        values["marker_found"] = marker_time is not None
        values["last_checked"] = marker_time.isoformat() if marker_time else None
        values["checked_age_days"] = _whole_days(marker_time, now) if marker_time else None
    updated = device
    for key, value in values.items():
        updated = set_device_attribute(updated, f"{parsed.output_bag}.{key}", value)
    return updated.model_copy(update={"status": DeviceStatus.OK})


async def _marker_time(
    service: DeviceDataService, device: DeviceContext, parsed: _Parsed
) -> datetime | None:
    key = render_placeholder_template(parsed.marker_storage_key, device).strip()
    if not key:
        # An absent attribute renders as ""; Store in DB refuses an empty key, so no real marker
        # can sit under it and a row stored that way must not make the device look checked.
        return None
    # A blocking database query: keep it off the event loop.
    record = await asyncio.to_thread(
        service.get_device_data, device_name=device.name, storage_key=key
    )
    return _as_utc(record.updated_at) if record is not None else None


def _missing_marker_message(parsed: _Parsed, names: list[str], total: int) -> str:
    shown = ", ".join(names[:_MAX_NAMED_DEVICES])
    more = len(names) - _MAX_NAMED_DEVICES
    listed = f"{shown} and {more} more" if more > 0 else shown
    return (
        f"No backup-check marker found under storage key {parsed.marker_storage_key!r} for "
        f"{len(names)} of {total} devices ({listed}). Check the key against the Store in DB "
        "step; last_checked and checked_age_days are empty for these devices."
    )


async def _report_missing_markers(parsed: _Parsed, names: list[str], total: int) -> None:
    """One warning run event for the whole step: a wrong key shows up as "all devices"."""
    message = _missing_marker_message(parsed, names, total)
    logger.warning("get-age-of-backup: %s", message)
    context = current_run_event_context()
    if context is None:
        return
    # emit_run_event is a blocking database write: keep it off the event loop.
    await asyncio.to_thread(
        emit_run_event,
        context,
        kind="backup_marker_missing",
        message=message,
        level="warning",
    )


async def _locate_all(
    root: Path, parsed: _Parsed, context: WorkflowContext, node_id: str
) -> tuple[dict[str, _Backup], dict[str, DeviceContext]]:
    """Phase 1 (git, all devices at once): the located backups and the devices that failed."""
    backups: dict[str, _Backup] = {}

    async def locate(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        try:
            backups[device_id] = await asyncio.to_thread(
                _locate_backup, root, device, parsed, context.run_id
            )
        except _DeviceProblem as problem:
            return Fail(code=problem.code, message=str(problem), failure=problem.failure)
        except Exception:
            logger.exception("get-age-of-backup failed for a device node_id=%s", node_id)
            raise  # the runner records the class name and a FailureInfo
        return device

    batch = await run_per_device(context, locate, node_id=node_id, step_id=_STEP_ID)
    return backups, batch.failed


async def _apply_markers(
    context: WorkflowContext,
    parsed: _Parsed,
    backups: dict[str, _Backup],
    node_id: str,
    now: datetime,
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    """Phase 2 (database, one device after the other): the ages, with the marker if asked."""
    without_marker: list[str] = []
    looked_up = 0  # devices whose marker was asked for, whether or not the lookup then worked
    db = get_db_session() if parsed.use_marker else None
    try:
        service = DeviceDataService(db) if db is not None else None

        async def apply(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
            nonlocal looked_up
            try:
                if service is not None:
                    looked_up += 1
                marker = await _marker_time(service, device, parsed) if service else None
                if service is not None and marker is None:
                    without_marker.append(device.name)
                return _with_ages(
                    device, parsed=parsed, backup=backups[device_id], marker_time=marker, now=now
                )
            except Exception:
                logger.exception("get-age-of-backup marker lookup failed node_id=%s", node_id)
                raise  # the runner records the class name and a FailureInfo

        # One session, one device after the other (concurrency=1).
        batch = await run_per_device(
            context, apply, node_id=node_id, step_id=_STEP_ID, concurrency=1, only=set(backups)
        )
    finally:
        if db is not None:
            db.close()
    if without_marker:
        await _report_missing_markers(parsed, without_marker, looked_up)
    return batch.ok, batch.failed


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # unused: nothing is stored, no device is contacted

    parsed = _parse(config)
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "get-age-of-backup started run_id=%s node_id=%s devices=%d use_marker=%s",
        log_run_id(run),
        node_id,
        len(context.devices),
        parsed.use_marker,
    )

    now = _utcnow()
    async with AsyncExitStack() as stack:
        root = await resolve_git_root(
            parsed.git_repository_id, stack, allow_stale=parsed.allow_stale
        )
        backups, located_failed = await _locate_all(root, parsed, context, node_id)
    marked_ok, marked_failed = await _apply_markers(context, parsed, backups, node_id, now)
    failed_by_id = {**located_failed, **marked_failed}
    # Outcomes keep the order of the incoming context.
    success = {i: marked_ok[i] for i in context.devices if i in marked_ok}
    failed = {i: failed_by_id[i] for i in context.devices if i in failed_by_id}

    logger.info(
        "get-age-of-backup finished success=%d failure=%d run_id=%s",
        len(success),
        len(failed),
        log_run_id(run),
    )
    return build_outcomes(context, success, failed)
