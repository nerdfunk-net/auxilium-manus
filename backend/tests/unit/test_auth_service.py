"""Tests for AuthService.ensure_initial_admin (doc/plans/FABE_BACKEND_ISSUES.md §4.4, §4.8)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.auth.auth_service import AuthService


class TestEnsureInitialAdmin(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AuthService(MagicMock())
        self.service.users = MagicMock()

    def test_sets_must_change_password_true_on_creation(self) -> None:
        self.service.users.get_by_username.return_value = None
        created = MagicMock()
        self.service.users.create_user.return_value = created

        result = self.service.ensure_initial_admin()

        self.assertIs(result, created)
        _args, kwargs = self.service.users.create_user.call_args
        self.assertTrue(kwargs["must_change_password"])

    def test_does_not_touch_an_existing_admin_row(self) -> None:
        existing = MagicMock()
        self.service.users.get_by_username.return_value = existing

        result = self.service.ensure_initial_admin()

        self.assertIs(result, existing)
        self.service.users.create_user.assert_not_called()
        self.service.users.update_user.assert_not_called()


if __name__ == "__main__":
    unittest.main()
