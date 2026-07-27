"""Tests that git credential resolution is scoped to global credentials only."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.git.auth import GitAuthenticationService


def test_resolve_credentials_scopes_to_global_only() -> None:
    mock_cred_mgr = MagicMock()
    mock_cred_mgr.list_credentials.return_value = [
        {"id": 1, "name": "deploy-token", "type": "token", "username": "git"},
    ]
    mock_cred_mgr.get_decrypted_password.return_value = "shh"

    with (
        patch("service_factory.build_credentials_service", return_value=mock_cred_mgr),
        patch("core.database.SessionLocal", return_value=MagicMock()),
    ):
        service = GitAuthenticationService()
        username, token, ssh_key_path = service.resolve_credentials(
            {"auth_type": "token", "credential_name": "deploy-token"}
        )

    mock_cred_mgr.list_credentials.assert_called_once_with(
        include_expired=False, acting_user_id=None
    )
    mock_cred_mgr.get_decrypted_password.assert_called_once_with(1, acting_user_id=None)
    assert username == "git"
    assert token == "shh"
    assert ssh_key_path is None


def test_resolve_credentials_treats_private_only_match_as_not_found() -> None:
    # Simulates the scoped list omitting a credential that only exists as
    # another user's private credential — git must fail closed, not resolve it.
    mock_cred_mgr = MagicMock()
    mock_cred_mgr.list_credentials.return_value = []

    with (
        patch("service_factory.build_credentials_service", return_value=mock_cred_mgr),
        patch("core.database.SessionLocal", return_value=MagicMock()),
    ):
        service = GitAuthenticationService()
        username, token, ssh_key_path = service.resolve_credentials(
            {"auth_type": "token", "credential_name": "someone-elses-private-cred"}
        )

    assert (username, token, ssh_key_path) == (None, None, None)
