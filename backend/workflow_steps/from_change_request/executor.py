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
import contextlib
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
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
from services.git.failure import GitOperationError
from services.git.paths import resolve_within_repo
from services.git.repo_lock import git_repo_lock
from services.git.tree_scope import async_scope, git_branch_scope
from workflow_steps.common.git_repository_loader import load_git_repository
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "from-change-request"


def _load_change_request(change_request_id: int) -> Any:
    from core.database import get_db_session
    from repositories.change_request_repository import ChangeRequestRepository

    db = get_db_session()
    try:
        return ChangeRequestRepository(db).get_by_id(change_request_id)
    finally:
        db.close()


@contextmanager
def _cr_tree(git_service: Any, repository: dict[str, Any], change_request: Any) -> Iterator[Path]:
    """Hold the repository lease, check out the change-request branch and restore the
    configured branch afterwards. The deploy is pinned: HEAD must be the reviewed commit."""
    with git_repo_lock(int(repository["id"])) as lease:
        repo = git_service.open_or_clone(repository)
        fetch_result = git_service.fetch(repository, repo=repo)
        if not fetch_result.success:
            raise fetch_result.error()
        with git_branch_scope(git_service, repo, repository, change_request.branch):
            head = repo.head.commit.hexsha
            reviewed = change_request.commit_sha
            if not reviewed:
                # staging always records the reviewed commit; without it nothing is pinned
                raise GitOperationError(
                    "The change request has no reviewed commit recorded, so the deploy cannot be "
                    "pinned. Nothing was deployed.",
                    failure=FailureInfo(phase="git", kind="ref_mismatch", hint="re_run_stage"),
                )
            if head != reviewed:
                raise GitOperationError(
                    "The change request branch moved after it was reviewed; the reviewed commit "
                    f"is {reviewed[:12]}, the branch is now at {head[:12]}. Nothing was "
                    "deployed.",
                    failure=FailureInfo(phase="git", kind="ref_mismatch", hint="re_run_stage"),
                )
            lease.ensure_held()
            yield git_service.get_repo_path(repository)


@asynccontextmanager
async def _maybe_async(cm: Any) -> AsyncIterator[Any]:
    """``async with`` over either an async scope or a plain ``nullcontext(None)``."""
    if hasattr(cm, "__aenter__"):
        async with cm as value:
            yield value
    else:
        yield None


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

    checkout = parse_bool_flag(config, "checkout_branch", default=True)
    load_configs = parse_bool_flag(config, "load_configs", default=True)

    logger.info(
        "%s started run_id=%s change_request_id=%s devices=%d",
        _STEP_ID,
        run.id,
        change_request_id,
        len(entries),
    )

    new_devices: dict[str, DeviceContext] = {}
    tree_cm: Any = contextlib.nullcontext(None)
    if (checkout or load_configs) and change_request.git_repository_id and change_request.branch:
        import service_factory

        git_service = service_factory.build_git_service()
        repository = load_git_repository(int(change_request.git_repository_id))
        tree_cm = async_scope(_cr_tree(git_service, repository, change_request))

    async with _maybe_async(tree_cm) as repo_root:
        for entry in entries:
            device = _build_device(entry)
            config_path = entry.get("config_path")
            if load_configs and repo_root is not None and config_path:
                # config_path comes from the stored snapshot: it must stay inside the tree (C5-08)
                target = resolve_within_repo(repo_root, str(config_path))
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
