"""workflows:release_ai is a protected permission (P3) and is seeded to no role but admin."""

from __future__ import annotations

import unittest

from core.models.rbac import Permission
from services.auth.rbac_seed import DEFAULT_PERMISSIONS, VIEWER_PERMISSIONS
from services.auth.rbac_service import _is_protected


class ReleaseAiPermissionTests(unittest.TestCase):
    def test_permission_is_in_the_catalog(self) -> None:
        self.assertIn("release_ai", {a for r, a, _ in DEFAULT_PERMISSIONS if r == "workflows"})

    def test_permission_is_protected(self) -> None:
        self.assertTrue(_is_protected(Permission(resource="workflows", action="release_ai")))

    def test_other_workflow_permissions_stay_delegable(self) -> None:
        for action in ("read", "write", "execute", "publish", "delete"):
            self.assertFalse(_is_protected(Permission(resource="workflows", action=action)))

    def test_viewer_does_not_hold_it(self) -> None:
        self.assertNotIn(("workflows", "release_ai"), set(VIEWER_PERMISSIONS))


if __name__ == "__main__":
    unittest.main()
