"""Tests for RBACService.has_permission precedence: user override beats role
grant beats default-deny, against a real in-memory SQLite-backed session."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.rbac import Permission, Role, RolePermission, UserPermission, UserRole
from core.models.users import User
from services.auth.rbac_service import RBACService


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    User.metadata.create_all(
        engine,
        tables=[
            User.__table__,
            Role.__table__,
            Permission.__table__,
            RolePermission.__table__,
            UserRole.__table__,
            UserPermission.__table__,
        ],
    )
    return sessionmaker(bind=engine)()


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, password_hash="hash", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class RBACServiceHasPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.service = RBACService(self.db)
        self.user = _make_user(self.db, "alice")

        self.permission = self.service.create_permission("workflows", "write", "Edit workflows")

    def test_default_deny_when_no_role_or_override(self) -> None:
        self.assertFalse(
            self.service.has_permission(self.user.id, "workflows", "write"),
        )

    def test_unknown_permission_denies(self) -> None:
        self.assertFalse(
            self.service.has_permission(self.user.id, "unknown", "action"),
        )

    def test_role_grant_allows(self) -> None:
        role = self.service.create_role("editor")
        self.service.assign_permission_to_role(role.id, self.permission.id, granted=True)
        self.service.assign_role_to_user(self.user.id, role.id)

        self.assertTrue(
            self.service.has_permission(self.user.id, "workflows", "write"),
        )

    def test_role_permission_not_granted_denies(self) -> None:
        role = self.service.create_role("editor")
        self.service.assign_permission_to_role(role.id, self.permission.id, granted=False)
        self.service.assign_role_to_user(self.user.id, role.id)

        self.assertFalse(
            self.service.has_permission(self.user.id, "workflows", "write"),
        )

    def test_user_override_allow_beats_no_role(self) -> None:
        self.service.assign_permission_to_user(self.user.id, self.permission.id, granted=True)

        self.assertTrue(
            self.service.has_permission(self.user.id, "workflows", "write"),
        )

    def test_user_override_deny_beats_role_grant(self) -> None:
        role = self.service.create_role("editor")
        self.service.assign_permission_to_role(role.id, self.permission.id, granted=True)
        self.service.assign_role_to_user(self.user.id, role.id)
        self.service.assign_permission_to_user(self.user.id, self.permission.id, granted=False)

        self.assertFalse(
            self.service.has_permission(self.user.id, "workflows", "write"),
        )

    def test_removing_override_falls_back_to_role_grant(self) -> None:
        role = self.service.create_role("editor")
        self.service.assign_permission_to_role(role.id, self.permission.id, granted=True)
        self.service.assign_role_to_user(self.user.id, role.id)
        self.service.assign_permission_to_user(self.user.id, self.permission.id, granted=False)
        self.service.remove_permission_from_user(self.user.id, self.permission.id)

        self.assertTrue(
            self.service.has_permission(self.user.id, "workflows", "write"),
        )

    def test_has_role(self) -> None:
        role = self.service.create_role("editor")
        self.service.assign_role_to_user(self.user.id, role.id)

        self.assertTrue(self.service.has_role(self.user.id, "editor"))
        self.assertFalse(self.service.has_role(self.user.id, "admin"))

    def test_get_user_permission_strings_merges_role_and_override(self) -> None:
        read_permission = self.service.create_permission("workflows", "read", "View workflows")
        role = self.service.create_role("editor")
        self.service.assign_permission_to_role(role.id, read_permission.id, granted=True)
        self.service.assign_role_to_user(self.user.id, role.id)
        self.service.assign_permission_to_user(self.user.id, self.permission.id, granted=True)

        self.assertEqual(
            self.service.get_user_permission_strings(self.user.id),
            ["workflows:read", "workflows:write"],
        )


if __name__ == "__main__":
    unittest.main()
