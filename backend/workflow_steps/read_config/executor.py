"""Executor for the read-config step."""

from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    render_device_template,
)
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.file_source_root import resolve_source_root
from workflow_steps.common.git_repository_loader import parse_repository_id
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "read-config"
_SOURCES = frozenset({"filesystem", "git"})


@dataclass(frozen=True)
class _ParsedReadConfig:
    source: str
    git_repository_id: int | None
    path_template: str
    overwrite_existing: bool


def _parse_read_config(config: dict[str, Any]) -> _ParsedReadConfig:
    source = str(config.get("source") or "filesystem").strip().lower()
    if source not in _SOURCES:
        raise ValueError(f"{_STEP_ID}: source must be one of {sorted(_SOURCES)}")

    raw_repository_id = config.get("git_repository_id")
    git_repository_id = parse_repository_id(raw_repository_id, step_id=_STEP_ID)
    if source == "git" and git_repository_id is None:
        raise ValueError(f"{_STEP_ID}: git_repository_id is required when source=git")

    path_template = str(config.get("path_template") or "").strip()
    if not path_template:
        raise ValueError(f"{_STEP_ID}: path_template is required")

    return _ParsedReadConfig(
        source=source,
        git_repository_id=git_repository_id,
        path_template=path_template,
        overwrite_existing=parse_bool_flag(config, "overwrite_existing"),
    )


def _resolve_target_path(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: unsafe path {relative_path!r}") from exc
    return target


async def _read_for_device(
    *,
    device_id: str,
    device: DeviceContext,
    root: Path,
    parsed: _ParsedReadConfig,
    context_run_id: str,
    artifact_service: ArtifactService,
) -> DeviceContext | Fail:
    """One device. ``ValueError`` / ``FileNotFoundError`` text is written by this step (relative
    paths); any other error (``PermissionError`` carries the absolute path) is reduced to its
    class name by the runner."""
    if device.running_config_ref is not None and not parsed.overwrite_existing:
        return device

    relative_path = render_device_template(
        parsed.path_template,
        device,
        options=TemplateRenderOptions(strict=True, run_id=context_run_id),
    )
    target = _resolve_target_path(root, relative_path)
    if not target.is_file():
        raise FileNotFoundError(f"config file not found: {relative_path}")

    content = await asyncio.to_thread(target.read_text, encoding="utf-8")
    if not content.strip():
        return Fail(
            "empty_config",
            f"config file is empty: {relative_path}",
            FailureInfo(phase="config", kind="invalid_response"),
        )
    ref = await artifact_service.store(
        content=content,
        kind="running_config",
        device_id=device_id,
        run_id=context_run_id,
    )
    return device.model_copy(
        update={
            "status": DeviceStatus.OK,
            "running_config_ref": ref,
            "capabilities": device.capabilities | {Capability.RUNNING_CONFIG},
        }
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
    del device_sessions  # unused: this step never connects to a device

    parsed = _parse_read_config(config)

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    logger.info(
        "read-config started run_id=%s node_id=%s devices=%d source=%s",
        log_run_id(run),
        node_id,
        len(context.devices),
        parsed.source,
    )

    async with AsyncExitStack() as stack:
        root = await resolve_source_root(
            source=parsed.source,
            git_repository_id=parsed.git_repository_id,
            stack=stack,
            allow_stale=parse_bool_flag(config, "allow_stale_repository"),
            step_id=_STEP_ID,
        )

        async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
            return await _read_for_device(
                device_id=device_id,
                device=device,
                root=root,
                parsed=parsed,
                context_run_id=context.run_id,
                artifact_service=artifact_service,
            )

        batch = await run_per_device(context, work, node_id=node_id, step_id=_STEP_ID)

    logger.info(
        "read-config finished success=%d failure=%d run_id=%s",
        len(batch.ok),
        len(batch.failed),
        log_run_id(run),
    )
    return build_outcomes(context, batch.ok, batch.failed)
