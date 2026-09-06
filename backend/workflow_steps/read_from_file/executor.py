"""Executor for the read-from-file step.

Reads a YAML or JSON file from the local export directory or a Git repository,
parses it once, and deep-merges the resulting mapping into every device's
attribute bag at a configurable destination path.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.database import get_db_session
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.general.general_settings_service import GeneralSettingsService
from services.git.paths import resolve_within_repo
from services.git.sync import clone_or_pull
from services.parsing import parse_structured_document
from services.parsing.structured_document import FORMATS as _FORMATS
from workflow_steps.common.attribute_merge import (
    merge_into_device_attribute,
    validate_merge_destination,
)
from workflow_steps.common.git_repository_loader import load_git_repository

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "read-from-file"
_SOURCES = frozenset({"filesystem", "git"})


@dataclass(frozen=True)
class _ParsedReadFromFile:
    source: str
    git_repository_id: int | None
    path: str
    fmt: str
    destination_path: str
    overwrite: bool


def _parse_bool(config: dict[str, Any], key: str) -> bool:
    value = config.get(key, False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _parse_config(config: dict[str, Any]) -> _ParsedReadFromFile:
    source = str(config.get("source") or "filesystem").strip().lower()
    if source not in _SOURCES:
        raise ValueError(f"{_STEP_ID}: source must be one of {sorted(_SOURCES)}")

    raw_repository_id = config.get("git_repository_id")
    git_repository_id = int(raw_repository_id) if raw_repository_id not in (None, "") else None
    if source == "git" and git_repository_id is None:
        raise ValueError(f"{_STEP_ID}: git_repository_id is required when source=git")

    path = str(config.get("path") or "").strip()
    if not path:
        raise ValueError(f"{_STEP_ID}: path is required")

    fmt = str(config.get("format") or "auto").strip().lower()
    if fmt not in _FORMATS:
        raise ValueError(f"{_STEP_ID}: format must be one of {sorted(_FORMATS)}")

    destination_path = str(config.get("destination_path") or "").strip()
    try:
        validate_merge_destination(destination_path)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: {exc}") from exc

    return _ParsedReadFromFile(
        source=source,
        git_repository_id=git_repository_id,
        path=path,
        fmt=fmt,
        destination_path=destination_path,
        overwrite=_parse_bool(config, "overwrite"),
    )


def _resolve_filesystem_root() -> Path:
    db = get_db_session()
    try:
        return GeneralSettingsService(db).resolved_export_directory()
    finally:
        db.close()


async def _resolve_git_root(git_repository_id: int, loop: asyncio.AbstractEventLoop) -> Path:
    repository = await loop.run_in_executor(None, lambda: load_git_repository(git_repository_id))
    return await loop.run_in_executor(None, lambda: clone_or_pull(repository))


def _fail_device(
    *, device: DeviceContext, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def _build_outcomes(
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
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
    del device_sessions  # unused: this step never connects to a device
    del artifact_service  # unused: parsed data is merged into the bag, not stored

    parsed = _parse_config(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "read-from-file started run_id=%s node_id=%s devices=%d source=%s format=%s destination=%s",
        run.id,
        node_id,
        len(context.devices),
        parsed.source,
        parsed.fmt,
        parsed.destination_path,
    )

    loop = asyncio.get_running_loop()
    if parsed.source == "git":
        root = await _resolve_git_root(parsed.git_repository_id, loop)
    else:
        root = await loop.run_in_executor(None, _resolve_filesystem_root)

    target = resolve_within_repo(root, parsed.path)
    if not await asyncio.to_thread(target.is_file):
        raise FileNotFoundError(f"{_STEP_ID}: file not found: {parsed.path}")

    text = await asyncio.to_thread(target.read_text, encoding="utf-8")
    document = parse_structured_document(text, fmt=parsed.fmt, filename=parsed.path)
    if not isinstance(document, dict):
        raise ValueError(
            f"{_STEP_ID}: {parsed.path} must parse to a mapping, "
            f"got {type(document).__name__}"
        )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_id, device in context.devices.items():
        try:
            success_devices[device_id] = merge_into_device_attribute(
                device, parsed.destination_path, document, overwrite=parsed.overwrite
            )
        except Exception as exc:  # defensive: destination shape is pre-validated
            failed_devices[device_id] = _fail_device(
                device=device,
                node_id=node_id,
                code=type(exc).__name__.lower(),
                message=str(exc),
            )

    logger.info(
        "read-from-file finished success=%d failure=%d keys=%d run_id=%s",
        len(success_devices),
        len(failed_devices),
        len(document),
        run.id,
    )
    return _build_outcomes(context, success_devices, failed_devices)
