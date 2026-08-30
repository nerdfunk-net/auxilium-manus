"""Tests for admin_reseed_rbac, in particular the remove_existing wipe path:
FK cascades must clear role/user assignments, and the calling admin must be
self-healed back into the admin role within the same call (no restart)."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings
from core.models.rbac import Permission, Role, RolePermission, UserPermission, UserRole
from core.models.users import User
from services.auth.rbac_seed import DEFAULT_PERMISSIONS, SYSTEM_ROLES, admin_reseed_rbac


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


class AdminReseedRbacTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.admin_user = User(
            username=settings.initial_username,
            password_hash="hash",
            is_active=True,
        )
        self.db.add(self.admin_user)
        self.db.commit()
        self.db.refresh(self.admin_user)

    def test_seed_creates_catalog_and_assigns_admin_role(self) -> None:
        result = admin_reseed_rbac(self.db, remove_existing=False)

        self.assertEqual(result.permissions_seeded, len(DEFAULT_PERMISSIONS))
        self.assertEqual(result.roles_seeded, len(SYSTEM_ROLES))
        self.assertFalse(result.removed_existing)

        admin_role = self.db.scalar(select(Role).where(Role.name == "admin"))
        self.assertIsNotNone(admin_role)
        user_roles = list(
            self.db.scalars(select(UserRole).where(UserRole.user_id == self.admin_user.id))
        )
        self.assertEqual([ur.role_id for ur in user_roles], [admin_role.id])

    def test_remove_existing_wipes_and_reseeds_without_locking_out_admin(self) -> None:
        admin_reseed_rbac(self.db, remove_existing=False)

        result = admin_reseed_rbac(self.db, remove_existing=True)

        self.assertTrue(result.removed_existing)
        self.assertEqual(result.permissions_seeded, len(DEFAULT_PERMISSIONS))
        self.assertEqual(result.roles_seeded, len(SYSTEM_ROLES))

        # Exactly one role/permission row per catalog entry — no stale
        # duplicates survived from before the wipe (the whole point of the
        # FK-cascade wipe, as opposed to just re-running the idempotent seed).
        self.assertEqual(len(list(self.db.scalars(select(Role)))), len(SYSTEM_ROLES))
        self.assertEqual(len(list(self.db.scalars(select(Permission)))), len(DEFAULT_PERMISSIONS))

        # The calling admin is self-healed back into the admin role within
        # this same call — exactly one assignment, not zero (locked out) or
        # two (a stale one plus a fresh one).
        new_admin_role = self.db.scalar(select(Role).where(Role.name == "admin"))
        user_roles = list(
            self.db.scalars(select(UserRole).where(UserRole.user_id == self.admin_user.id))
        )
        self.assertEqual(len(user_roles), 1)
        self.assertEqual(user_roles[0].role_id, new_admin_role.id)


if __name__ == "__main__":
    unittest.main()
