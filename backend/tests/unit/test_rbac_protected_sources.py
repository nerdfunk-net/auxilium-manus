"""sources.*:write / :delete are protected permissions (policy P3): only an admin may grant them."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.domain_exceptions import AccessDeniedError
from core.models.rbac import Permission, Role, RolePermission, UserPermission, UserRole
from core.models.users import User
from services.auth.rbac_service import RBACService, _is_protected


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


class IsProtectedTests(unittest.TestCase):
    def test_source_write_and_delete_are_protected(self) -> None:
        for resource in ("sources.ise", "sources.catalyst_center", "sources.nautobot"):
            for action in ("write", "delete"):
                with self.subTest(resource=resource, action=action):
                    self.assertTrue(_is_protected(Permission(resource=resource, action=action)))

    def test_source_read_and_query_stay_delegable(self) -> None:
        self.assertFalse(_is_protected(Permission(resource="sources.ise", action="read")))
        self.assertFalse(_is_protected(Permission(resource="sources.batfish", action="query")))

    def test_unrelated_resources_are_not_protected(self) -> None:
        self.assertFalse(_is_protected(Permission(resource="workflows", action="write")))
        self.assertFalse(_is_protected(Permission(resource="sources", action="write")))

    def test_existing_protected_resources_are_unchanged(self) -> None:
        self.assertTrue(_is_protected(Permission(resource="users", action="read")))
        self.assertTrue(
            _is_protected(Permission(resource="secret_manager.connections", action="read"))
        )


class ProtectedSourcePermissionGrantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.service = RBACService(self.db)
        admin_role = self.service.create_role("admin", is_system=True)
        self.admin_user = _make_user(self.db, "admin_user")
        self.non_admin_user = _make_user(self.db, "non_admin_user")
        self.target_user = _make_user(self.db, "target_user")
        self.service.assign_role_to_user(self.admin_user.id, admin_role.id)
        self.source_write = self.service.create_permission("sources.catalyst_center", "write")
        # the non-admin holds it, so P2 (grant only what you hold) is not what blocks the grant
        self.service.assign_permission_to_user(self.non_admin_user.id, self.source_write.id)

    def test_non_admin_cannot_grant_source_write_via_custom_role(self) -> None:
        custom_role = self.service.create_role("custom")
        with self.assertRaises(AccessDeniedError):
            self.service.assign_permission_to_role(
                custom_role.id, self.source_write.id, actor_user_id=self.non_admin_user.id
            )

    def test_non_admin_cannot_grant_source_write_via_user_override(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.assign_permission_to_user(
                self.target_user.id, self.source_write.id, actor_user_id=self.non_admin_user.id
            )

    def test_admin_can_grant_source_write(self) -> None:
        self.service.assign_permission_to_user(
            self.target_user.id, self.source_write.id, actor_user_id=self.admin_user.id
        )
        self.assertTrue(
            self.service.has_permission(self.target_user.id, "sources.catalyst_center", "write")
        )

    def test_non_admin_can_still_grant_source_read(self) -> None:
        source_read = self.service.create_permission("sources.catalyst_center", "read")
        self.service.assign_permission_to_user(self.non_admin_user.id, source_read.id)
        self.service.assign_permission_to_user(
            self.target_user.id, source_read.id, actor_user_id=self.non_admin_user.id
        )
        self.assertTrue(
            self.service.has_permission(self.target_user.id, "sources.catalyst_center", "read")
        )
