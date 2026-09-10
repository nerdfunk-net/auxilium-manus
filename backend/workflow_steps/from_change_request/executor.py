"""Executor for the from-change-request step.

The inventory step for a **deploy workflow**. When a run is dispatched by a
change-request approval (``run.change_request_id`` is set), this step:

* rebuilds the device list from the identity snapshot the ``open-change-request``
  step captured on the change request — so the deploy workflow needs no
  upstream ``get-nautobot-devices`` / ``get-git-devices``;
* checks out the change request's ``manus/cr-{id}`` branch into the repository
  working tree (``checkout_branch``);
* loads each device's reviewed config file as ``running_config``
  (``load_configs``), so a deploy workflow can be as short as
  ``from-change-request → upload-config → configure-replace-config``.

See ``doc/CICD_PIPELINE.md`` §3.3.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.git_repository_loader import load_git_repository

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "from-change-request"


def _bool(config: dict[str, Any], key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _load_change_request(change_request_id: int) -> Any:
    from core.database import get_db_session
    from repositories.change_request_repository import ChangeRequestRepository

    db = get_db_session()
    try:
        return ChangeRequestRepository(db).get_by_id(change_request_id)
    finally:
        db.close()


def _checkout_cr_branch(git_service: Any, repository: dict[str, Any], branch: str) -> Path:
    repo = git_service.open_or_clone(repository)
    fetch_result = git_service.fetch(repository, repo=repo)
    if not fetch_result.success:
        raise RuntimeError(fetch_result.message)
    git_service.checkout_new_branch(repo, branch, f"origin/{branch}")
    return git_service.get_repo_path(repository)


def _build_device(entry: dict[str, Any]) -> DeviceContext:
    name = str(entry.get("name") or entry.get("id") or "").strip()
    return DeviceContext(
        id=str(entry.get("id") or name),
        name=name,
        hostname=str(entry.get("hostname") or name),
        platform=entry.get("platform") or None,
        network_driver=entry.get("network_driver") or None,
        primary_ip4=entry.get("primary_ip4") or None,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.PENDING,
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
    del device_sessions

    change_request_id = getattr(run, "change_request_id", None)
    if not change_request_id:
        raise ValueError(
            f"{_STEP_ID}: this run was not dispatched by a change-request approval. "
            "Use this step only in a deploy workflow."
        )

    change_request = _load_change_request(int(change_request_id))
    if change_request is None:
        raise ValueError(f"{_STEP_ID}: change request {change_request_id} not found")
    entries = list(change_request.devices or [])
    if not entries:
        raise ValueError(
            f"{_STEP_ID}: change request {change_request_id} has no device snapshot "
            "(it predates this feature — re-run the stage workflow)."
        )

    checkout = _bool(config, "checkout_branch", True)
    load_configs = _bool(config, "load_configs", True)

    logger.info(
        "%s started run_id=%s change_request_id=%s devices=%d",
        _STEP_ID,
        run.id,
        change_request_id,
        len(entries),
    )

    repo_root: Path | None = None
    if (checkout or load_configs) and change_request.git_repository_id and change_request.branch:
        import service_factory

        git_service = service_factory.build_git_service()
        repository = load_git_repository(int(change_request.git_repository_id))
        repo_root = await asyncio.to_thread(
            _checkout_cr_branch, git_service, repository, change_request.branch
        )

    new_devices: dict[str, DeviceContext] = {}
    for entry in entries:
        device = _build_device(entry)
        config_path = entry.get("config_path")
        if load_configs and repo_root is not None and config_path:
            target = repo_root / str(config_path)
            if target.is_file():
                content = await asyncio.to_thread(target.read_text, encoding="utf-8")
                ref = await artifact_service.store(
                    content=content,
                    kind="running_config",
                    device_id=device.id,
                    run_id=context.run_id,
                )
                device = device.model_copy(
                    update={
                        "running_config_ref": ref,
                        "capabilities": device.capabilities | {Capability.RUNNING_CONFIG},
                    }
                )
            else:
                logger.warning(
                    "%s: config file %s missing on branch %s (device %s)",
                    _STEP_ID,
                    config_path,
                    change_request.branch,
                    device.name,
                )
        new_devices[device.id] = device

    metadata = {
        **context.metadata,
        f"{node_id}.change_request": {
            "change_request_id": change_request.id,
            "uuid": change_request.uuid,
            "branch": change_request.branch,
            "commit_sha": change_request.commit_sha,
            "git_repository_id": change_request.git_repository_id,
            "devices": len(new_devices),
        },
    }
    logger.info(
        "%s rebuilt %d device(s) from change_request_id=%s branch=%s run_id=%s",
        _STEP_ID,
        len(new_devices),
        change_request_id,
        change_request.branch,
        run.id,
    )
    return [
        StepOutcome(
            name="success",
            context=context.model_copy(
                update={
                    "devices": {**context.devices, **new_devices},
                    "metadata": metadata,
                }
            ),
        )
    ]
