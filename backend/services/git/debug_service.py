"""Debug and diagnostic operations for git repositories."""

from __future__ import annotations

import logging
import os
import ssl
from datetime import datetime
from pathlib import Path
from typing import Any

from services.git.config import set_git_author
from services.git.env import set_ssl_env
from services.git.shared_utils import get_git_repo_by_id, git_repo_manager

logger = logging.getLogger(__name__)


class GitDebugService:
    """Encapsulates all debug/diagnostic operations for a git repository."""

    def test_read(self, repo_id: int) -> dict[str, Any]:
        """Test reading the debug sentinel file from the repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
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
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        test_content = (
            f"Cockpit Debug Test\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
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
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
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
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        repo = get_git_repo_by_id(repo_id)
        repo_path = Path(repo.working_dir)
        test_file_path = repo_path / ".cockpit_debug_test.txt"

        username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
        auth_type = repository.get("auth_type", "token")
        has_token_auth = bool(username and token)
        has_ssh_auth = bool(ssh_key_path)

        if auth_type == "ssh_key" and not has_ssh_auth:
            return {
                "success": False,
                "message": "SSH key authentication configured but no SSH key found",
                "details": {
                    "error": "Push requires SSH key credential",
                    "error_type": "AuthenticationRequired",
                    "suggestion": (
                        "Configure an SSH key credential for this repository"
                        " to enable push operations"
                    ),
                },
            }
        elif auth_type == "token" and not has_token_auth:
            return {
                "success": False,
                "message": "No credentials configured for push",
                "details": {
                    "error": "Push requires authentication credentials",
                    "error_type": "AuthenticationRequired",
                    "suggestion": (
                        "Configure a token credential for this repository"
                        " to enable push operations"
                    ),
                },
            }
        elif auth_type == "none":
            return {
                "success": False,
                "message": "Authentication is disabled for this repository",
                "details": {
                    "error": "Push requires authentication",
                    "error_type": "AuthenticationRequired",
                    "suggestion": (
                        "Set authentication type to 'Token' or 'SSH Key'"
                        " to enable push operations"
                    ),
                },
            }

        try:
            test_content = (
                f"Cockpit Debug Push Test\n"
                f"Timestamp: {datetime.now().isoformat()}\n"
                f"Repository: {repository['name']}\n"
            )
            test_file_path.write_text(test_content)

            try:
                repo.index.add([".cockpit_debug_test.txt"])
            except Exception as add_error:
                return {
                    "success": False,
                    "message": f"Failed to stage file: {str(add_error)}",
                    "details": {
                        "error": str(add_error),
                        "error_type": type(add_error).__name__,
                        "stage": "git_add",
                    },
                }

            commit_sha = None
            try:
                commit_message = f"Debug push test - {datetime.now().isoformat()}"
                with set_git_author(repository, repo):
                    commit = repo.index.commit(commit_message)
                commit_sha = commit.hexsha[:8]
            except Exception as commit_error:
                if "nothing to commit" in str(commit_error).lower():
                    return {
                        "success": False,
                        "message": "No changes to push (test file unchanged)",
                        "details": {
                            "error": str(commit_error),
                            "error_type": "NoChanges",
                            "suggestion": (
                                "The test file already exists with the same content."
                                " Use Write test first."
                            ),
                        },
                    }
                return {
                    "success": False,
                    "message": f"Failed to commit changes: {str(commit_error)}",
                    "details": {
                        "error": str(commit_error),
                        "error_type": type(commit_error).__name__,
                        "stage": "git_commit",
                    },
                }

            original_url = None
            try:
                origin = repo.remote("origin")
                original_url = list(origin.urls)[0]

                with set_ssl_env(repository):
                    with git_auth_service.setup_auth_environment(repository) as (
                        auth_url,
                        _username,
                        _token,
                        _ssh_key_path,
                    ):
                        if auth_type != "ssh_key":
                            origin.set_url(auth_url)

                        try:
                            push_info = origin.push(
                                refspec=f"{repository['branch']}:{repository['branch']}"
                            )

                            if auth_type != "ssh_key" and original_url:
                                try:
                                    origin.set_url(original_url)
                                except Exception:
                                    pass

                            if push_info and len(push_info) > 0:
                                push_result = push_info[0]
                                if push_result.flags & push_result.ERROR:
                                    return {
                                        "success": False,
                                        "message": f"Push failed: {push_result.summary}",
                                        "details": {
                                            "error": push_result.summary,
                                            "error_type": "PushError",
                                            "commit_sha": commit_sha,
                                            "suggestion": (
                                "Check repository permissions and credentials"
                            ),
                                        },
                                    }
                                return {
                                    "success": True,
                                    "message": "Push test successful - changes pushed to remote",
                                    "details": {
                                        "commit_sha": commit_sha,
                                        "commit_message": commit_message,
                                        "branch": repository["branch"],
                                        "remote": "origin",
                                        "file_path": str(test_file_path),
                                        "push_summary": push_result.summary,
                                        "verified": True,
                                    },
                                }
                            return {
                                "success": False,
                                "message": "Push completed but no feedback received",
                                "details": {
                                    "error": "No push info returned",
                                    "error_type": "UnknownPushResult",
                                    "commit_sha": commit_sha,
                                },
                            }

                        except Exception as push_error:
                            if auth_type != "ssh_key" and original_url:
                                try:
                                    origin.set_url(original_url)
                                except Exception:
                                    pass

                            error_message = str(push_error)
                            if (
                                "permission denied" in error_message.lower()
                                or "403" in error_message
                            ):
                                suggestion = (
                                    "Authentication failed or insufficient permissions."
                                    " Check that the token has write access."
                                )
                            elif "could not resolve host" in error_message.lower():
                                suggestion = (
                                    "Network error: Cannot reach remote repository."
                                    " Check network connectivity."
                                )
                            elif "authentication failed" in error_message.lower():
                                suggestion = (
                                    "Credentials are invalid."
                                    " Update the token in credential settings."
                                )
                            else:
                                suggestion = (
                                    "Check repository configuration and network connectivity"
                                )

                            return {
                                "success": False,
                                "message": f"Failed to push: {error_message}",
                                "details": {
                                    "error": error_message,
                                    "error_type": type(push_error).__name__,
                                    "stage": "git_push",
                                    "commit_sha": commit_sha,
                                    "suggestion": suggestion,
                                },
                            }

            except Exception as remote_error:
                return {
                    "success": False,
                    "message": f"Failed to configure remote: {str(remote_error)}",
                    "details": {
                        "error": str(remote_error),
                        "error_type": type(remote_error).__name__,
                        "stage": "configure_remote",
                    },
                }

        except PermissionError as e:
            return {
                "success": False,
                "message": "Permission denied for file operations",
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
                "message": f"Unexpected error during push test: {str(e)}",
                "details": {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "file_path": str(test_file_path),
                },
            }

    def get_diagnostics(self, repo_id: int, git_auth_service) -> dict[str, Any]:
        """Return comprehensive diagnostic information for the repository."""
        repository = git_repo_manager.get_repository(repo_id)
        if not repository:
            raise ValueError(f"Repository {repo_id} not found")

        diagnostics: dict[str, Any] = {
            "repository_info": {
                "id": repository["id"],
                "name": repository["name"],
                "url": repository["url"],
                "branch": repository["branch"],
                "is_active": repository["is_active"],
                "verify_ssl": repository.get("verify_ssl", True),
            },
            "access_test": {},
            "file_system": {},
            "git_status": {},
            "ssl_info": {},
            "credentials": {},
            "push_capability": {},
        }

        try:
            repo = get_git_repo_by_id(repo_id)
            repo_path = Path(repo.working_dir)

            diagnostics["access_test"] = {
                "accessible": True,
                "path": str(repo_path),
                "exists": repo_path.exists(),
            }

            try:
                diagnostics["file_system"] = {
                    "readable": os.access(str(repo_path), os.R_OK),
                    "writable": os.access(str(repo_path), os.W_OK),
                    "executable": os.access(str(repo_path), os.X_OK),
                    "path": str(repo_path),
                }
            except Exception as e:
                diagnostics["file_system"] = {"error": str(e), "error_type": type(e).__name__}

            try:
                diagnostics["git_status"] = {
                    "is_dirty": repo.is_dirty(untracked_files=True),
                    "active_branch": repo.active_branch.name,
                    "head_commit": (
                        repo.head.commit.hexsha[:8] if repo.head.is_valid() else "no commits"
                    ),
                    "remotes": [r.name for r in repo.remotes],
                    "has_origin": "origin" in [r.name for r in repo.remotes],
                }
            except Exception as e:
                diagnostics["git_status"] = {"error": str(e), "error_type": type(e).__name__}

        except Exception as e:
            diagnostics["access_test"] = {
                "accessible": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }

        try:
            if not repository.get("verify_ssl", True):
                diagnostics["ssl_info"] = {
                    "verification": "disabled",
                    "note": "SSL verification is disabled for this repository",
                }
            else:
                diagnostics["ssl_info"] = {
                    "verification": "enabled",
                    "ssl_version": ssl.OPENSSL_VERSION,
                }
        except Exception as e:
            diagnostics["ssl_info"] = {"error": str(e), "error_type": type(e).__name__}

        try:
            username, token, ssh_key_path = git_auth_service.resolve_credentials(repository)
            auth_type = repository.get("auth_type", "token")

            diagnostics["credentials"] = {
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

            diagnostics["push_capability"] = {
                "status": push_status,
                "message": push_message,
                "has_credentials": has_credentials,
                "has_remote": has_remote,
                "remote_url": remote_url,
                "can_push": has_credentials and has_remote,
            }

        except Exception as e:
            diagnostics["credentials"] = {"error": str(e), "error_type": type(e).__name__}
            diagnostics["push_capability"] = {
                "status": "error",
                "message": f"Failed to assess push capability: {str(e)}",
                "can_push": False,
            }

        return {"success": True, "repository_id": repo_id, "diagnostics": diagnostics}
