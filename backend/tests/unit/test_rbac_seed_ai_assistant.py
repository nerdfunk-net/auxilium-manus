"""Tests for the ai-assistant role/permission seed and ensure_ai_assistant_user —
see doc/ai_workflows/PROCESS.md for why this account exists and why it must be
created inactive with a curated, non-admin permission set."""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.models.rbac import Permission, Role, RolePermission, UserPermission, UserRole
from core.models.users import User
from services.auth.rbac_seed import (
    AI_ASSISTANT_PERMISSIONS,
    AI_ASSISTANT_USERNAME,
    ensure_ai_assistant_user,
    seed_rbac,
)


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


class AiAssistantSeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)

    def test_ensure_ai_assistant_user_creates_inactive_user(self) -> None:
        user = ensure_ai_assistant_user(self.db)

        self.assertEqual(user.username, AI_ASSISTANT_USERNAME)
        self.assertFalse(user.is_active)

    def test_ensure_ai_assistant_user_is_idempotent(self) -> None:
        first = ensure_ai_assistant_user(self.db)
        second = ensure_ai_assistant_user(self.db)

        self.assertEqual(first.id, second.id)
        rows = list(self.db.scalars(select(User).where(User.username == AI_ASSISTANT_USERNAME)))
        self.assertEqual(len(rows), 1)

    def test_seed_rbac_grants_exactly_the_curated_permissions(self) -> None:
        seed_rbac(self.db)

        role = self.db.scalar(select(Role).where(Role.name == "ai-assistant"))
        self.assertIsNotNone(role)
        self.assertTrue(role.is_system)

        granted = {
            (p.resource, p.action)
            for p in self.db.scalars(
                select(Permission)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )
        }
        self.assertEqual(granted, set(AI_ASSISTANT_PERMISSIONS))

    def test_ai_assistant_role_excludes_dangerous_permissions(self) -> None:
        # Never workflows:execute/publish/delete, change_requests:approve,
        # credentials:reveal, or anything rbac.*/users/system.*/secret_manager.* —
        # the whole point of a curated allowlist instead of "grant everything".
        seed_rbac(self.db)
        role = self.db.scalar(select(Role).where(Role.name == "ai-assistant"))
        granted = {
            (p.resource, p.action)
            for p in self.db.scalars(
                select(Permission)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            )
        }
        forbidden = {
            ("workflows", "execute"),
            ("workflows", "publish"),
            ("workflows", "delete"),
            ("change_requests", "approve"),
            ("credentials", "reveal"),
            ("credentials", "write"),
            ("rbac.roles", "write"),
            ("users", "write"),
        }
        self.assertEqual(granted & forbidden, set())

    def test_seed_rbac_is_idempotent_for_ai_assistant_grants(self) -> None:
        seed_rbac(self.db)
        seed_rbac(self.db)

        role = self.db.scalar(select(Role).where(Role.name == "ai-assistant"))
        rows = list(
            self.db.scalars(select(RolePermission).where(RolePermission.role_id == role.id))
        )
        self.assertEqual(len(rows), len(AI_ASSISTANT_PERMISSIONS))


if __name__ == "__main__":
    unittest.main()
