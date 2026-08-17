"""Tests for UserPreferenceService. dashboard_layout is stored as PostgreSQL
JSONB, which in-memory SQLite cannot compile, so the repository is mocked
rather than exercised against a real session (see doc/refactoring rules on
SQLite-only unit tests requiring no PostgreSQL-only features)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.models.user_preferences import UserPreference
from models.user_preferences import DashboardLayoutUpdate
from services.users.user_preference_service import UserPreferenceService


class UserPreferenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = UserPreferenceService.__new__(UserPreferenceService)
        self.mock_repo = MagicMock()
        self.service._repo = self.mock_repo

    def test_get_dashboard_layout_returns_none_when_no_row(self) -> None:
        self.mock_repo.get_by_user_id.return_value = None

        result = self.service.get_dashboard_layout(1)

        self.assertIsNone(result.layout)
        self.mock_repo.get_by_user_id.assert_called_once_with(1)

    def test_get_dashboard_layout_returns_stored_layout(self) -> None:
        preference = UserPreference(user_id=1, dashboard_layout={"version": 1})
        self.mock_repo.get_by_user_id.return_value = preference

        result = self.service.get_dashboard_layout(1)

        self.assertEqual(result.layout, {"version": 1})

    def test_update_dashboard_layout_upserts_and_returns_layout(self) -> None:
        saved = UserPreference(user_id=1, dashboard_layout={"version": 1, "layouts": {}})
        self.mock_repo.upsert_dashboard_layout.return_value = saved

        result = self.service.update_dashboard_layout(
            1, DashboardLayoutUpdate(layout={"version": 1, "layouts": {}})
        )

        self.mock_repo.upsert_dashboard_layout.assert_called_once_with(
            1, {"version": 1, "layouts": {}}
        )
        self.assertEqual(result.layout, {"version": 1, "layouts": {}})


if __name__ == "__main__":
    unittest.main()
