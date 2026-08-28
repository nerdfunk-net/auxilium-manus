"""Regression test: GitRepositoryService.create_repository must persist auth_type.

Previously create_repository silently dropped the submitted auth_type,
defaulting every newly created repository to "token" until a subsequent
edit — a hard blocker for SSH-keyed remotes (e.g. the workflow
version-control repository) working correctly on first save.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from services.git.repository_service import GitRepositoryService


def test_create_repository_persists_auth_type() -> None:
    service = GitRepositoryService(MagicMock())
    service._repo = MagicMock()
    service._repo.name_exists.return_value = False
    service._repo.create.return_value = MagicMock(id=1)

    service.create_repository(
        {
            "name": "workflows-repo",
            "category": "workflows",
            "url": "https://example.com/workflows.git",
            "auth_type": "ssh_key",
            "credential_name": "workflows-ssh-key",
        }
    )

    _, kwargs = service._repo.create.call_args
    assert kwargs["auth_type"] == "ssh_key"


def test_create_repository_defaults_auth_type_to_token() -> None:
    service = GitRepositoryService(MagicMock())
    service._repo = MagicMock()
    service._repo.name_exists.return_value = False
    service._repo.create.return_value = MagicMock(id=1)

    service.create_repository(
        {
            "name": "configs-repo",
            "category": "device_configs",
            "url": "https://example.com/configs.git",
        }
    )

    _, kwargs = service._repo.create.call_args
    assert kwargs["auth_type"] == "token"
