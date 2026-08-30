"""RBAC anti-elevation: system-role mutations require the actor to hold the
admin role (H3). See services/auth/rbac_service.py::RBACService._require_admin_actor."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.domain_exceptions import AccessDeniedError
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


class RBACElevationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.service = RBACService(self.db)
        self.admin_role = self.service.create_role("admin", is_system=True)
        self.viewer_role = self.service.create_role("viewer", is_system=True)
        self.admin_user = _make_user(self.db, "admin_user")
        self.non_admin_user = _make_user(self.db, "non_admin_user")
        self.target_user = _make_user(self.db, "target_user")
        self.service.assign_role_to_user(self.admin_user.id, self.admin_role.id)

    def test_non_admin_actor_cannot_assign_system_role(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.assign_role_to_user(
                self.target_user.id, self.admin_role.id, actor_user_id=self.non_admin_user.id
            )

    def test_admin_actor_can_assign_system_role(self) -> None:
        self.service.assign_role_to_user(
            self.target_user.id, self.admin_role.id, actor_user_id=self.admin_user.id
        )
        self.assertTrue(self.service.has_role(self.target_user.id, "admin"))

    def test_non_admin_actor_cannot_assign_permission_to_system_role(self) -> None:
        permission = self.service.create_permission("workflows", "write")
        with self.assertRaises(AccessDeniedError):
            self.service.assign_permission_to_role(
                self.admin_role.id, permission.id, actor_user_id=self.non_admin_user.id
            )

    def test_non_admin_actor_cannot_remove_permission_from_system_role(self) -> None:
        permission = self.service.create_permission("workflows", "write")
        self.service.assign_permission_to_role(self.admin_role.id, permission.id)
        with self.assertRaises(AccessDeniedError):
            self.service.remove_permission_from_role(
                self.admin_role.id, permission.id, actor_user_id=self.non_admin_user.id
            )

    def test_assign_role_to_user_by_name_without_actor_still_succeeds(self) -> None:
        self.service.assign_role_to_user_by_name(self.target_user.id, "admin")
        self.assertTrue(self.service.has_role(self.target_user.id, "admin"))

    def test_non_admin_actor_cannot_create_system_role(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.create_role(
                "new-system-role", is_system=True, actor_user_id=self.non_admin_user.id
            )

    def test_admin_actor_can_create_system_role(self) -> None:
        role = self.service.create_role(
            "new-system-role", is_system=True, actor_user_id=self.admin_user.id
        )
        self.assertTrue(role.is_system)

    def test_non_admin_actor_can_assign_non_system_role(self) -> None:
        custom_role = self.service.create_role("custom")
        self.service.assign_role_to_user(
            self.target_user.id, custom_role.id, actor_user_id=self.non_admin_user.id
        )
        self.assertTrue(self.service.has_role(self.target_user.id, "custom"))


if __name__ == "__main__":
    unittest.main()
