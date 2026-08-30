"""Area 4 — Git-backed workflow steps (plan §7.3).

Direct executor calls against the lab Gitea repo. Clones land under a
per-test monkeypatched git data root.
"""

from __future__ import annotations

import pytest

import services.git.paths as git_paths
from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
from tests.integration.helpers.aio import run as arun
from workflow_steps.get_git_devices.executor import execute as get_git_devices
from workflow_steps.git_clone.executor import execute as git_clone
from workflow_steps.git_pull.executor import execute as git_pull

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("require_gitea")]


@pytest.fixture(autouse=True)
def git_data_root(tmp_path, monkeypatch):
    root = tmp_path / "git-data"
    root.mkdir()
    monkeypatch.setattr(git_paths, "_GIT_DATA_ROOT", root)
    return root


@pytest.fixture
def run():
    class _Run:
        id = 1
        uuid = "itest-run-git"
        workflow_id = 1

    return _Run()


def _ctx(run) -> WorkflowContext:
    return WorkflowContext(run_id=run.uuid, workflow_id=str(run.workflow_id))


def _call(executor, run, config, node_id="n1"):
    async def _body():
        return await executor(
            config=config,
            context=_ctx(run),
            run=run,
            artifact_service=InMemoryArtifactService(),
            node_id=node_id,
            device_sessions=None,
        )

    return arun(_body())


def test_git_clone(run, git_repository) -> None:
    outcomes = _call(git_clone, run, {"git_repository_id": git_repository["id"]})
    success = next(o for o in outcomes if o.name == "success")
    op = success.context.metadata["n1.git_operation"]
    assert op["operation"] == "clone"
    assert op["success"] is True


def test_git_pull_after_clone(run, git_repository) -> None:
    _call(git_clone, run, {"git_repository_id": git_repository["id"]}, node_id="c1")
    outcomes = _call(git_pull, run, {"git_repository_id": git_repository["id"]}, node_id="p1")
    op = next(o for o in outcomes if o.name == "success").context.metadata["p1.git_operation"]
    assert op["operation"] == "pull"
    assert op["commits_pulled"] == 0


def test_get_git_devices(run, git_repository) -> None:
    outcomes = _call(
        get_git_devices,
        run,
        {
            "git_repository_id": git_repository["id"],
            "filename_pattern": "*.yaml",
            "directory": "devices",
        },
    )
    ctx = next(o for o in outcomes if o.name == "success").context
    if ctx.metadata["n1.files_read"] == 0:
        pytest.xfail("lab repo has no devices/*.yaml — add one per plan §5.8")
    assert ctx.metadata["n1.files_read"] >= 1
    assert len(ctx.devices) >= 1


def test_get_git_devices_missing_repo_id_raises(run) -> None:
    with pytest.raises(ValueError):
        _call(get_git_devices, run, {"filename_pattern": "*.yaml"})


def test_git_clone_missing_repo_id_returns_failure(run) -> None:
    outcomes = _call(git_clone, run, {})
    failure = next(o for o in outcomes if o.name == "failure")
    op = failure.context.metadata["n1.git_operation"]
    assert op["success"] is False
