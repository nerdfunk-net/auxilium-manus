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


class RBACGrantPolicyTests(unittest.TestCase):
    """P1-P7 policy tests (doc/plans/FABE_BACKEND_ISSUES.md §2.7)."""

    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.service = RBACService(self.db)
        self.admin_role = self.service.create_role("admin", is_system=True)
        self.admin_user = _make_user(self.db, "admin_user")
        self.service.assign_role_to_user(self.admin_user.id, self.admin_role.id)
        self.other_admin_user = _make_user(self.db, "other_admin_user")
        self.service.assign_role_to_user(self.other_admin_user.id, self.admin_role.id)
        self.non_admin_user = _make_user(self.db, "non_admin_user")
        self.target_user = _make_user(self.db, "target_user")
        self.users_write = self.service.create_permission("users", "write")
        self.workflows_write = self.service.create_permission("workflows", "write")

    def test_users_write_holder_cannot_override_protected_permission_for_self(self) -> None:
        # non_admin_user holds users:write (a protected resource) and tries to grant
        # it to themself — blocked by P1 (self-target) before P3 is even reached.
        self.service.assign_permission_to_user(self.non_admin_user.id, self.users_write.id)
        with self.assertRaises(AccessDeniedError):
            self.service.assign_permission_to_user(
                self.non_admin_user.id,
                self.users_write.id,
                actor_user_id=self.non_admin_user.id,
            )

    def test_users_write_holder_cannot_override_permission_they_do_not_hold(self) -> None:
        self.service.assign_permission_to_user(self.non_admin_user.id, self.users_write.id)
        with self.assertRaises(AccessDeniedError):
            self.service.assign_permission_to_user(
                self.target_user.id,
                self.workflows_write.id,
                actor_user_id=self.non_admin_user.id,
            )

    def test_users_write_holder_cannot_touch_admin_user(self) -> None:
        self.service.assign_permission_to_user(self.non_admin_user.id, self.workflows_write.id)
        with self.assertRaises(AccessDeniedError):
            self.service.assign_permission_to_user(
                self.other_admin_user.id,
                self.workflows_write.id,
                actor_user_id=self.non_admin_user.id,
            )

    def test_non_admin_cannot_remove_system_role_from_user(self) -> None:
        viewer_role = self.service.create_role("viewer", is_system=True)
        self.service.assign_role_to_user(self.target_user.id, viewer_role.id)
        with self.assertRaises(AccessDeniedError):
            self.service.remove_role_from_user(
                self.target_user.id, viewer_role.id, actor_user_id=self.non_admin_user.id
            )

    def test_last_admin_cannot_lose_admin_role(self) -> None:
        # P6 is an invariant, not an actor-gated rule: an actor able to legitimately
        # touch an admin target is by definition also an admin, so removing one of
        # (at least) two admins never trips it — it only fires once exactly one
        # admin remains, which callers reach via the actor_user_id=None (internal)
        # path, same as seed/lifespan callers.
        self.service.remove_role_from_user(
            self.other_admin_user.id, self.admin_role.id, actor_user_id=None
        )
        with self.assertRaises(AccessDeniedError):
            self.service.remove_role_from_user(
                self.admin_user.id, self.admin_role.id, actor_user_id=None
            )

    def test_non_admin_cannot_add_unheld_permission_to_custom_role(self) -> None:
        custom_role = self.service.create_role("custom")
        with self.assertRaises(AccessDeniedError):
            self.service.assign_permission_to_role(
                custom_role.id, self.workflows_write.id, actor_user_id=self.non_admin_user.id
            )

    def test_non_admin_cannot_assign_custom_role_containing_unheld_permission(self) -> None:
        custom_role = self.service.create_role("custom")
        self.service.assign_permission_to_role(custom_role.id, self.workflows_write.id)
        with self.assertRaises(AccessDeniedError):
            self.service.assign_role_to_user(
                self.target_user.id, custom_role.id, actor_user_id=self.non_admin_user.id
            )

    def test_system_role_cannot_be_renamed(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.service.update_role(self.admin_role.id, name="root")

    def test_system_role_description_can_still_be_updated(self) -> None:
        role = self.service.update_role(self.admin_role.id, description="Full access")
        self.assertEqual(role.description, "Full access")

    def test_actor_none_bypasses_policy(self) -> None:
        # Internal callers (seed, lifespan) pass actor_user_id=None.
        custom_role = self.service.create_role("internal-role")
        self.service.assign_permission_to_role(custom_role.id, self.workflows_write.id)
        self.service.assign_role_to_user(self.target_user.id, custom_role.id)
        self.service.assign_permission_to_user(self.target_user.id, self.users_write.id)
        self.assertTrue(self.service.has_role(self.target_user.id, "internal-role"))

    def test_admin_can_do_all_of_the_above(self) -> None:
        custom_role = self.service.create_role("custom")
        self.service.assign_permission_to_role(
            custom_role.id, self.workflows_write.id, actor_user_id=self.admin_user.id
        )
        self.service.assign_role_to_user(
            self.target_user.id, custom_role.id, actor_user_id=self.admin_user.id
        )
        self.service.assign_permission_to_user(
            self.target_user.id, self.users_write.id, actor_user_id=self.admin_user.id
        )
        self.service.update_role(custom_role.id, name="custom-renamed")
        self.service.remove_role_from_user(
            self.target_user.id, custom_role.id, actor_user_id=self.admin_user.id
        )
        self.assertFalse(self.service.has_role(self.target_user.id, "custom-renamed"))


class UserServiceSelfProtectionTests(unittest.TestCase):
    """P1/P4/P6 for delete/deactivate (doc/plans/FABE_BACKEND_ISSUES.md §2.4)."""

    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.rbac = RBACService(self.db)
        self.admin_role = self.rbac.create_role("admin", is_system=True)
        self.admin_user = _make_user(self.db, "admin_user")
        self.rbac.assign_role_to_user(self.admin_user.id, self.admin_role.id)

    def _user_service(self):
        from services.users.user_service import UserService

        return UserService(self.db)

    def test_actor_cannot_delete_self(self) -> None:
        service = self._user_service()
        with self.assertRaises(AccessDeniedError):
            service.delete_user(self.admin_user.id, actor_user_id=self.admin_user.id)

    def test_actor_cannot_deactivate_self(self) -> None:
        service = self._user_service()
        with self.assertRaises(AccessDeniedError):
            service.set_active(self.admin_user.id, False, actor_user_id=self.admin_user.id)

    def test_cannot_remove_last_admin(self) -> None:
        # See the comment on test_last_admin_cannot_lose_admin_role: only an
        # actor_user_id=None (internal) caller can reach a sole remaining admin
        # without first tripping P1 (self) or P4 (non-admin touching an admin).
        service = self._user_service()
        with self.assertRaises(AccessDeniedError):
            service.delete_user(self.admin_user.id, actor_user_id=None)


if __name__ == "__main__":
    unittest.main()
