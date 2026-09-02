"""Debug and diagnostic operations for git repositories."""

from __future__ import annotations

import logging
import os
import ssl
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.git.config import set_git_author
from services.git.env import build_git_env_overrides
from services.git.repository_service import GitRepositoryService
from services.git.shared_utils import get_git_repo_by_id

logger = logging.getLogger(__name__)


def _repository_info_section(repository: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": repository["id"],
        "name": repository["name"],
        "url": repository["url"],
        "branch": repository["branch"],
        "is_active": repository["is_active"],
        "verify_ssl": repository.get("verify_ssl", True),
    }


def _collect_local_repo_diagnostics(repo_id: int) -> dict[str, Any]:
    sections: dict[str, Any] = {
        "access_test": {},
        "file_system": {},
        "git_status": {},
    }

    try:
        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)

        sections["access_test"] = {
            "accessible": True,
            "path": str(repo_path),
            "exists": repo_path.exists(),
        }

        try:
            sections["file_system"] = {
                "readable": os.access(str(repo_path), os.R_OK),
                "writable": os.access(str(repo_path), os.W_OK),
                "executable": os.access(str(repo_path), os.X_OK),
                "path": str(repo_path),
            }
        except Exception as e:
            sections["file_system"] = {"error": str(e), "error_type": type(e).__name__}

        try:
            sections["git_status"] = {
                "is_dirty": repo.is_dirty(untracked_files=True),
                "active_branch": repo.active_branch.name,
                "head_commit": (
                    repo.head.commit.hexsha[:8] if repo.head.is_valid() else "no commits"
                ),
                "remotes": [r.name for r in repo.remotes],
                "has_origin": "origin" in [r.name for r in repo.remotes],
            }
        except Exception as e:
            sections["git_status"] = {"error": str(e), "error_type": type(e).__name__}

    except Exception as e:
        sections["access_test"] = {
            "accessible": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }

    return sections


def _collect_ssl_diagnostics(repository: dict[str, Any]) -> dict[str, Any]:
    try:
        if not repository.get("verify_ssl", True):
            return {
                "verification": "disabled",
                "note": "SSL verification is disabled for this repository",
            }
        return {
            "verification": "enabled",
            "ssl_version": ssl.OPENSSL_VERSION,
        }
    except Exception as e:
        return {"error": str(e), "error_type": type(e).__name__}


def _collect_auth_and_push_diagnostics(
    repo_id: int,
    repository: dict[str, Any],
    git_auth_service: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
        auth_type = repository.get("auth_type", "token")

        credentials = {
            "credential_name": repository.get("credential_name", "none"),
            "auth_type": auth_type,
            "has_username": bool(username),
            "has_token": bool(token),
            "has_ssh_key": bool(ssh_key_path),
            "token_length": len(token) if token else 0,
            "authentication": "configured" if (username and token) or ssh_key_path else "none",
        }

        if auth_type == "ssh_key":
            has_credentials = bool(ssh_key_path)
        elif auth_type == "token":
            has_credentials = bool(username and token)
        else:
            has_credentials = False

        has_remote = False
        remote_url = "unknown"
        try:
            repo = get_git_repo_by_id(repo_id)
            if "origin" in [r.name for r in repo.remotes]:
                has_remote = True
                origin = repo.remote("origin")
                remote_url = list(origin.urls)[0] if origin.urls else "unknown"
        except Exception:
            pass

        if has_credentials and has_remote:
            push_status, push_message = "ready", "Push capability is configured and ready"
        elif not has_credentials:
            push_status, push_message = (
                "no_credentials",
                "Push requires authentication credentials",
            )
        elif not has_remote:
            push_status, push_message = "no_remote", "No remote 'origin' configured"
        else:
            push_status, push_message = "unknown", "Push capability status unclear"

        push_capability = {
            "status": push_status,
            "message": push_message,
            "has_credentials": has_credentials,
            "has_remote": has_remote,
            "remote_url": remote_url,
            "can_push": has_credentials and has_remote,
        }

        return credentials, push_capability

    except Exception as e:
        return (
            {"error": str(e), "error_type": type(e).__name__},
            {
                "status": "error",
                "message": f"Failed to assess push capability: {str(e)}",
                "can_push": False,
            },
        )


def _debug_result(success: bool, message: str, **details: Any) -> dict[str, Any]:
    return {"success": success, "message": message, "details": details}


def _require_push_auth(
    repository: dict[str, Any],
    username: str | None,
    token: str | None,
    ssh_key_path: str | None,
) -> dict[str, Any] | None:
    auth_type = repository.get("auth_type", "token")
    has_token_auth = bool(username and token)
    has_ssh_auth = bool(ssh_key_path)

    if auth_type == "ssh_key" and not has_ssh_auth:
        return _debug_result(
            False,
            "SSH key authentication configured but no SSH key found",
            error="Push requires SSH key credential",
            error_type="AuthenticationRequired",
            suggestion=(
                "Configure an SSH key credential for this repository"
                " to enable push operations"
            ),
        )
    if auth_type == "token" and not has_token_auth:
        return _debug_result(
            False,
            "No credentials configured for push",
            error="Push requires authentication credentials",
            error_type="AuthenticationRequired",
            suggestion=(
                "Configure a token credential for this repository to enable push operations"
            ),
        )
    if auth_type == "none":
        return _debug_result(
            False,
            "Authentication is disabled for this repository",
            error="Push requires authentication",
            error_type="AuthenticationRequired",
            suggestion=(
                "Set authentication type to 'Token' or 'SSH Key' to enable push operations"
            ),
        )
    return None


def _stage_debug_sentinel(
    repo: Any,
    test_file_path: Path,
    repository: dict[str, Any],
) -> dict[str, Any] | None:
    test_content = (
        f"Cockpit Debug Push Test\n"
        f"Timestamp: {datetime.now(UTC).isoformat()}\n"
        f"Repository: {repository['name']}\n"
    )
    test_file_path.write_text(test_content)

    try:
        repo.index.add([".cockpit_debug_test.txt"])
    except Exception as add_error:
        return _debug_result(
            False,
            f"Failed to stage file: {str(add_error)}",
            error=str(add_error),
            error_type=type(add_error).__name__,
            stage="git_add",
        )
    return None


def _commit_debug_change(
    repo: Any,
    repository: dict[str, Any],
) -> tuple[str, str] | dict[str, Any]:
    try:
        commit_message = f"Debug push test - {datetime.now(UTC).isoformat()}"
        with set_git_author(repository, repo):
            commit = repo.index.commit(commit_message)
        return commit.hexsha[:8], commit_message
    except Exception as commit_error:
        if "nothing to commit" in str(commit_error).lower():
            return _debug_result(
                False,
                "No changes to push (test file unchanged)",
                error=str(commit_error),
                error_type="NoChanges",
                suggestion=(
                    "The test file already exists with the same content."
                    " Use Write test first."
                ),
            )
        return _debug_result(
            False,
            f"Failed to commit changes: {str(commit_error)}",
            error=str(commit_error),
            error_type=type(commit_error).__name__,
            stage="git_commit",
        )


def _push_error_suggestion(error_message: str) -> str:
    if "permission denied" in error_message.lower() or "403" in error_message:
        return (
            "Authentication failed or insufficient permissions."
            " Check that the token has write access."
        )
    if "could not resolve host" in error_message.lower():
        return (
            "Network error: Cannot reach remote repository."
            " Check network connectivity."
        )
    if "authentication failed" in error_message.lower():
        return "Credentials are invalid. Update the token in credential settings."
    return "Check repository configuration and network connectivity"


def _restore_origin_url(origin: Any, original_url: str | None, auth_type: str) -> None:
    if auth_type != "ssh_key" and original_url:
        try:
            origin.set_url(original_url)
        except Exception:
            pass


def _push_debug_commit(
    *,
    repo: Any,
    repository: dict[str, Any],
    auth_type: str,
    commit_sha: str,
    commit_message: str,
    test_file_path: Path,
    git_auth_service: Any,
) -> dict[str, Any]:
    try:
        origin = repo.remote("origin")
        original_url = list(origin.urls)[0]

        with git_auth_service.setup_auth_environment(repository) as (
            auth_url,
            _username,
            _token,
            _ssh_key_path,
        ):
            overrides = build_git_env_overrides(
                repository,
                ssh_key_path=_ssh_key_path if auth_type == "ssh_key" else None,
            )
            if auth_type != "ssh_key":
                origin.set_url(auth_url)

            try:
                with repo.git.custom_environment(**overrides):
                    push_info = origin.push(
                        refspec=f"{repository['branch']}:{repository['branch']}"
                    )

                _restore_origin_url(origin, original_url, auth_type)

                if push_info and len(push_info) > 0:
                    push_result = push_info[0]
                    if push_result.flags & push_result.ERROR:
                        return _debug_result(
                            False,
                            f"Push failed: {push_result.summary}",
                            error=push_result.summary,
                            error_type="PushError",
                            commit_sha=commit_sha,
                            suggestion=(
                                "Check repository permissions and credentials"
                            ),
                        )
                    return _debug_result(
                        True,
                        "Push test successful - changes pushed to remote",
                        commit_sha=commit_sha,
                        commit_message=commit_message,
                        branch=repository["branch"],
                        remote="origin",
                        file_path=str(test_file_path),
                        push_summary=push_result.summary,
                        verified=True,
                    )
                return _debug_result(
                    False,
                    "Push completed but no feedback received",
                    error="No push info returned",
                    error_type="UnknownPushResult",
                    commit_sha=commit_sha,
                )

            except Exception as push_error:
                _restore_origin_url(origin, original_url, auth_type)

                error_message = str(push_error)
                return _debug_result(
                    False,
                    f"Failed to push: {error_message}",
                    error=error_message,
                    error_type=type(push_error).__name__,
                    stage="git_push",
                    commit_sha=commit_sha,
                    suggestion=_push_error_suggestion(error_message),
                )

    except Exception as remote_error:
        return _debug_result(
            False,
            f"Failed to configure remote: {str(remote_error)}",
            error=str(remote_error),
            error_type=type(remote_error).__name__,
            stage="configure_remote",
        )


class GitDebugService:
    """Encapsulates all debug/diagnostic operations for a git repository."""

    def __init__(self, repos: GitRepositoryService | None = None) -> None:
        self._repos = repos or GitRepositoryService()

    def test_read(self, repo_id: int) -> dict[str, Any]:
        """Test reading the debug sentinel file from the repository."""
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id, self._repos)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        if not test_file_path.exists():
            return {
                "success": False,
                "message": "Test file does not exist",
                "details": {
                    "file_path": str(test_file_path),
                    "repository_path": str(repo_path),
                    "exists": False,
                    "suggestion": "Use the 'Write' operation to create the test file first",
                },
            }

        try:
            content = test_file_path.read_text()
            return {
                "success": True,
                "message": "File read successfully",
                "details": {
                    "file_path": str(test_file_path),
                    "content": content,
                    "size_bytes": len(content),
                    "readable": True,
                },
            }
        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied reading file",
                "details": {
                    "error": str(e),
                    "file_path": str(test_file_path),
                    "error_type": "PermissionError",
                    "suggestion": "Check file system permissions for the repository directory",
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error reading file: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }

    def test_write(self, repo_id: int) -> dict[str, Any]:
        """Test writing the debug sentinel file to the repository."""
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id, self._repos)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        test_content = (
            f"Cockpit Debug Test\n"
            f"Timestamp: {datetime.now(UTC).isoformat()}\n"
            f"Repository: {repository['name']}\n"
        )

        try:
            test_file_path.write_text(test_content)

            if not test_file_path.exists():
                return {
                    "success": False,
                    "message": "File write appeared to succeed but file does not exist",
                    "details": {
                        "file_path": str(test_file_path),
                        "error_type": "VerificationError",
                    },
                }

            written_content = test_file_path.read_text()
            success = written_content == test_content

            repo_status = "unknown"
            try:
                repo_status = (
                    "modified (file created but not committed)"
                    if repo.is_dirty(untracked_files=True)
                    else "clean"
                )
            except Exception:
                repo_status = "status check failed"

            return {
                "success": success,
                "message": (
                    "File written successfully"
                    if success
                    else "File written but verification failed"
                ),
                "details": {
                    "file_path": str(test_file_path),
                    "content_length": len(test_content),
                    "verified": success,
                    "git_status": repo_status,
                    "writable": True,
                },
            }

        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied writing file",
                "details": {
                    "error": str(e),
                    "file_path": str(test_file_path),
                    "error_type": "PermissionError",
                    "suggestion": "Check file system permissions for the repository directory",
                    "directory_writable": os.access(str(repo_path), os.W_OK),
                },
            }
        except OSError as e:
            return {
                "success": False,
                "message": f"OS error writing file: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": "OSError",
                    "file_path": str(test_file_path),
                    "suggestion": "Check disk space and file system health",
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error writing file: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }

    def test_delete(self, repo_id: int) -> dict[str, Any]:
        """Test deleting the debug sentinel file from the repository."""
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id, self._repos)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        if not test_file_path.exists():
            return {
                "success": False,
                "message": "Test file does not exist, nothing to delete",
                "details": {"file_path": str(test_file_path), "exists": False},
            }

        try:
            test_file_path.unlink()

            if test_file_path.exists():
                return {
                    "success": False,
                    "message": "File deletion appeared to succeed but file still exists",
                    "details": {
                        "file_path": str(test_file_path),
                        "error_type": "VerificationError",
                    },
                }

            repo_status = "unknown"
            try:
                repo_status = (
                    "modified (file deleted but not committed)"
                    if repo.is_dirty(untracked_files=True)
                    else "clean"
                )
            except Exception:
                repo_status = "status check failed"

            return {
                "success": True,
                "message": "File deleted successfully",
                "details": {
                    "file_path": str(test_file_path),
                    "verified": True,
                    "git_status": repo_status,
                },
            }

        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied deleting file",
                "details": {
                    "error": str(e),
                    "file_path": str(test_file_path),
                    "error_type": "PermissionError",
                    "suggestion": "Check file system permissions for the file",
                },
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error deleting file: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }

    def test_push(self, repo_id: int, git_auth_service) -> dict[str, Any]:
        """Test pushing a commit to the remote repository."""
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id, self._repos)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
        auth_type = repository.get("auth_type", "token")

        auth_error = _require_push_auth(repository, username, token, ssh_key_path)
        if auth_error is not None:
            return auth_error

        try:
            stage_error = _stage_debug_sentinel(repo, test_file_path, repository)
            if stage_error is not None:
                return stage_error

            commit_result = _commit_debug_change(repo, repository)
            if isinstance(commit_result, dict):
                return commit_result
            commit_sha, commit_message = commit_result

            return _push_debug_commit(
                repo=repo,
                repository=repository,
                auth_type=auth_type,
                commit_sha=commit_sha,
                commit_message=commit_message,
                test_file_path=test_file_path,
                git_auth_service=git_auth_service,
            )

        except PermissionError as e:
            return _debug_result(
                False,
                "Permission denied for file operations",
                error=str(e),
                file_path=str(test_file_path),
                error_type="PermissionError",
                suggestion="Check file system permissions for the repository directory",
            )
        except Exception as e:
            return _debug_result(
                False,
                f"Unexpected error during push test: {str(e)}",
                error=str(e),
                error_type=type(e).__name__,
                file_path=str(test_file_path),
            )

    def get_diagnostics(self, repo_id: int, git_auth_service) -> dict[str, Any]:
        """Return comprehensive diagnostic information for the repository."""
        repository = self._repos.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        diagnostics: dict[str, Any] = {
            "repository_info": _repository_info_section(repository),
            "access_test": {},
            "file_system": {},
            "git_status": {},
            "ssl_info": {},
            "credentials": {},
            "push_capability": {},
        }

        diagnostics.update(_collect_local_repo_diagnostics(repo_id))
        diagnostics["ssl_info"] = _collect_ssl_diagnostics(repository)

        creds_section, push_section = _collect_auth_and_push_diagnostics(
            repo_id, repository, git_auth_service
        )
        diagnostics["credentials"] = creds_section
        diagnostics["push_capability"] = push_section

        return {"success": True, "repository_id": repo_id, "diagnostics": diagnostics}
