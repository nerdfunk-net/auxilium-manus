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
        self.service.users.count.return_value = 0
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


    def test_initial_admin_not_recreated_when_users_exist(self) -> None:
        self.service.users.get_by_username.return_value = None
        self.service.users.count.return_value = 3

        self.assertIsNone(self.service.ensure_initial_admin())
        self.service.users.create_user.assert_not_called()

    def test_recover_recreates_the_initial_admin(self) -> None:
        self.service.users.get_by_username.return_value = None
        self.service.users.count.return_value = 3
        created = MagicMock()
        self.service.users.create_user.return_value = created

        self.assertIs(self.service.ensure_initial_admin(recover=True), created)
