"""Area 2 — Git service against the lab Gitea repo.

Requires: a reachable Gitea at ``GIT_TEST_REPO_URL`` with a valid
``GIT_TEST_REPO_TOKEN``, and ``ALLOW_LOOPBACK_SOURCE_URLS=true`` (Gitea is on
loopback). Clones land under a per-test tmp dir (monkeypatched git data root).
"""

from __future__ import annotations

import uuid

import pytest
from git import Repo

import service_factory
import services.git.paths as git_paths
from services.git.content_search_service import GitContentSearchService
from services.git.device_service import GitDeviceService
from services.git.repository_service import GitRepositoryService
from services.git.sync import clone_or_pull
from services.git.version_control_service import GitVersionControlService
from tests.unit._git_repo_builder import make_repo_with_remote

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("require_gitea")]


@pytest.fixture(autouse=True)
def git_data_root(tmp_path, monkeypatch):
    root = tmp_path / "git-data"
    root.mkdir()
    monkeypatch.setattr(git_paths, "_GIT_DATA_ROOT", root)
    return root


@pytest.fixture
def repo_dict(git_repository):
    return dict(git_repository["repository"])


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
def test_repository_service_crud(db) -> None:
    service = GitRepositoryService(db)
    name = f"itest-crud-{uuid.uuid4().hex[:8]}"
    repo_id = service.create_repository(
        {"name": name, "category": "device_configs", "url": "http://example.invalid/x.git"}
    )
    fetched = service.get_repository(repo_id)
    assert set(fetched) >= {
        "id", "name", "category", "url", "branch", "auth_type", "credential_name",
        "path", "verify_ssl", "is_active", "sync_status",
    }
    assert service.update_repository(repo_id, {"branch": "develop"}) is True
    assert service.get_repository(repo_id)["branch"] == "develop"
    assert service.delete_repository(repo_id, hard_delete=True) is True
    assert service.get_repository(repo_id) is None


# --------------------------------------------------------------------------- #
# Live Gitea operations
# --------------------------------------------------------------------------- #
def test_clone_checks_out_main(repo_dict) -> None:
    git_service = service_factory.build_git_service()
    git_service.clone(repo_dict)
    path = git_service.get_repo_path(repo_dict)
    assert path.is_dir()
    repo = Repo(path)
    assert not repo.bare
    assert repo.active_branch.name == repo_dict.get("branch", "main")


def test_open_or_clone_is_idempotent(repo_dict) -> None:
    git_service = service_factory.build_git_service()
    first = git_service.open_or_clone(repo_dict)
    second = git_service.open_or_clone(repo_dict)
    assert first.working_dir == second.working_dir


def test_pull_up_to_date_reports_zero(repo_dict) -> None:
    git_service = service_factory.build_git_service()
    git_service.clone(repo_dict)
    result = git_service.pull(repo_dict)
    assert result.success
    assert result.commits_pulled == 0  # nothing new since the clone


def test_branches_and_commits(git_repository, repo_dict) -> None:
    clone_or_pull(repo_dict)
    repo_id = git_repository["id"]

    branches = {b["name"] for b in GitVersionControlService().get_branches(repo_id)}
    assert repo_dict.get("branch", "main") in branches

    commits = GitVersionControlService().get_commits(repo_id, repo_dict.get("branch", "main"))
    assert commits
    assert {"hash", "message", "author"} <= set(commits[0])


def test_device_discovery(repo_dict) -> None:
    devices, files_read = GitDeviceService().fetch_devices(repo_dict, "*.yaml", "devices")
    if files_read == 0:
        pytest.xfail("lab repo has no devices/*.yaml — add one per plan §5.8")
    assert devices
    first = devices[0]
    assert "name" in first


def test_content_search(repo_dict) -> None:
    repo_path = clone_or_pull(repo_dict)
    matches, scanned = GitContentSearchService().search(
        repo_path,
        directory="",
        file_filter="*",
        recursive=True,
        include_history=False,
        search_text="a",
        case_sensitive=False,
    )
    assert scanned >= 1


def test_wrong_token_surfaces_git_command_error() -> None:
    """A bad token fails as a typed ``GitCommandError`` — no raw traceback leak.

    Creates a throwaway repo row + credential (real commits, cleaned up in
    ``finally``) so the shared ``git_repository`` fixture stays valid.
    """
    from git.exc import GitCommandError

    import core.database as db_mod
    from services.credentials.credentials_service import CredentialsService
    from services.git.repository_service import GitRepositoryService
    from tests.integration.helpers import env as env_helpers

    cfg = env_helpers.git_repo()
    session = db_mod.SessionLocal()
    cred = None
    repo_id = None
    try:
        cred = CredentialsService(session).create_credential(
            name="itest-git-badtoken",
            username="git",
            cred_type="token",
            password="not-a-valid-token",
            source="general",
            visibility="global",
        )
        repo_id = GitRepositoryService(session).create_repository(
            {
                "name": "itest-badtoken",
                "category": "device_configs",
                "url": cfg.url,
                "branch": cfg.branch,
                "auth_type": "token",
                "credential_name": "itest-git-badtoken",
                "verify_ssl": cfg.verify_ssl,
            }
        )
        repo_dict = GitRepositoryService(session).get_repository(repo_id)
        with pytest.raises(GitCommandError):
            service_factory.build_git_service().clone(repo_dict)
    finally:
        if repo_id is not None:
            GitRepositoryService(session).delete_repository(repo_id, hard_delete=True)
        if cred is not None:
            CredentialsService(session).delete_credential(int(cred["id"]))
        session.close()


# --------------------------------------------------------------------------- #
# Offline fallback (no Gitea required)
# --------------------------------------------------------------------------- #
def test_offline_local_clone_commit_push(tmp_path) -> None:
    work, remote = make_repo_with_remote(tmp_path)
    assert (work / ".git").is_dir()
    clone = tmp_path / "clone"
    Repo.clone_from(str(remote), str(clone))
    (clone / "new.txt").write_text("hello")
    cloned = Repo(str(clone))
    cloned.index.add(["new.txt"])
    cloned.index.commit("add new.txt")
    cloned.remote().push()
    assert "new.txt" in Repo(str(remote)).head.commit.tree
