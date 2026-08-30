"""Phase 2 — mutation tests (opt-in).

Every test here writes to a shared lab system and MUST restore prior state in
a ``finally`` / fixture teardown. They only run with ``--run-mutations``
(``@pytest.mark.mutations`` is skipped otherwise — see ``conftest.py``).

Only ``git-push`` is implemented end to end today; the device / Nautobot
mutations are scaffolded with their teardown contract and skip until the lab
fixtures they need (a writable scratch area that is guaranteed not to touch the
baseline) are wired up — see plan §9.
"""

from __future__ import annotations

import uuid

import pytest
from git import Repo

import service_factory
import services.git.paths as git_paths
from services.git.auth import GitAuthenticationService

pytestmark = [pytest.mark.integration, pytest.mark.mutations]


@pytest.fixture(autouse=True)
def git_data_root(tmp_path, monkeypatch):
    root = tmp_path / "git-data"
    root.mkdir()
    monkeypatch.setattr(git_paths, "_GIT_DATA_ROOT", root)
    return root


def _delete_remote_branch(repo_dict: dict, branch: str) -> None:
    auth = GitAuthenticationService()
    username, token, _ = auth.resolve_credentials(repo_dict)
    push_url = auth.build_auth_url(repo_dict["url"], username, token)
    git_service = service_factory.build_git_service()
    local = Repo(git_service.get_repo_path(repo_dict))
    try:
        local.git.push(push_url, "--delete", branch)
    except Exception:  # noqa: BLE001 — best-effort teardown
        pass


@pytest.mark.usefixtures("require_gitea")
def test_git_push_to_scratch_branch(git_repository) -> None:
    repo_dict = dict(git_repository["repository"])
    scratch = f"itest/{uuid.uuid4().hex[:12]}"
    repo_dict["branch"] = scratch

    try:
        # Clone default branch, then branch off + write a file + push.
        git_service = service_factory.build_git_service()
        repo = git_service.open_or_clone(dict(git_repository["repository"]))
        repo.git.checkout("-b", scratch)
        marker = f"itest-{uuid.uuid4().hex}.txt"
        (git_service.get_repo_path(repo_dict) / marker).write_text("integration marker\n")
        repo.index.add([marker])
        repo.index.commit(f"itest scratch commit {scratch}")

        result = git_service.push(repo_dict, repo=repo)
        assert result.success

        # Verify the commit is on the remote.
        auth = GitAuthenticationService()
        username, token, _ = auth.resolve_credentials(repo_dict)
        remote_refs = repo.git.ls_remote(
            auth.build_auth_url(repo_dict["url"], username, token), scratch
        )
        assert scratch in remote_refs
    finally:
        _delete_remote_branch(repo_dict, scratch)


@pytest.mark.skip(reason="Phase-2 scaffold — needs a rendered-config source step (plan §9)")
def test_deploy_config_and_revert() -> None:
    """snmp-server contact itest-<uuid> → assert running config reflects it → remove it."""


@pytest.mark.skip(reason="Phase-2 scaffold — needs a writable flash: path guarantee (plan §9)")
def test_upload_config_and_delete() -> None:
    """SCP a small file to bootflash:, verify via dir, then delete it."""


@pytest.mark.skip(reason="Phase-2 scaffold — needs a lab location safe from the baseline (plan §9)")
def test_add_and_remove_nautobot_device() -> None:
    """Create device itest-<uuid>, resolve it via the source service, update a CF, delete it."""
