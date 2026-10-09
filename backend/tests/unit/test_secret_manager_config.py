"""load_connection_config: missing/inactive connection and credential resolution (SM11)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.secret_manager.config import load_connection_config

_CONN = {
    "id": 7,
    "name": "net",
    "backend": "openbao",
    "verify_ssl": True,
    "is_active": True,
    "credential_name": "sm-auth",
    "backend_config": {"addr": "https://v", "mount": "m"},
}


def _patched(connection: dict | None, *, auth=None):
    service = MagicMock()
    service.get_connection.return_value = connection
    manager = MagicMock()
    if isinstance(auth, Exception):
        manager.secret_manager_auth.side_effect = auth
    else:
        manager.secret_manager_auth.return_value = auth
    return (
        patch(
            "services.secret_manager.connection_service.SecretManagerConnectionService",
            return_value=service,
        ),
        patch("services.secret_manager.config.CredentialManager", return_value=manager),
        manager,
    )


class LoadConnectionConfigTests(unittest.TestCase):
    def test_missing_connection(self) -> None:
        a, b, _ = _patched(None)
        with a, b, self.assertRaisesRegex(ValueError, "not found"):
            load_connection_config(7, MagicMock())

    def test_inactive_connection(self) -> None:
        a, b, _ = _patched({**_CONN, "is_active": False})
        with a, b, self.assertRaisesRegex(ValueError, "is not active"):
            load_connection_config(7, MagicMock())

    def test_no_credential_name_gives_empty_auth(self) -> None:
        a, b, manager = _patched({**_CONN, "credential_name": None})
        with a, b:
            cfg = load_connection_config(7, MagicMock())
        self.assertEqual((cfg.auth_id, cfg.auth_secret), ("", ""))
        manager.secret_manager_auth.assert_not_called()

    def test_ssh_credential_rejected_with_connection_name(self) -> None:
        a, b, _ = _patched(_CONN, auth=ValueError("SSH credentials are not allowed"))
        with a, b, self.assertRaisesRegex(ValueError, "'net'.*SSH credentials"):
            load_connection_config(7, MagicMock())

    def test_happy_path_returns_resolved_username_and_password(self) -> None:
        a, b, _ = _patched(_CONN, auth=SimpleNamespace(username="role", password="sid"))
        with a, b:
            cfg = load_connection_config(7, MagicMock())
        self.assertEqual((cfg.id, cfg.name, cfg.backend), (7, "net", "openbao"))
        self.assertEqual((cfg.auth_id, cfg.auth_secret), ("role", "sid"))


if __name__ == "__main__":
    unittest.main()
