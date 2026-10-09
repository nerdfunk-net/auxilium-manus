"""Private inventories follow their owner on rename and go away on delete (S14 / R6)."""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.models.inventories import Inventory
from core.models.rbac import Permission, Role, RolePermission, UserPermission, UserRole
from core.models.users import User
from repositories.inventory_repository import InventoryRepository
from repositories.user_repository import UserRepository
from services.users.inventory_orphans import warn_about_orphaned_inventories
from services.users.user_service import UserService


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
            Inventory.__table__,
        ],
    )
    return sessionmaker(bind=engine)()


class InventoryOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.alice = User(username="alice", password_hash="h", is_active=True)
        self.db.add(self.alice)
        self.db.commit()
        self._add_inventory("alice-private", "private", "alice")
        self._add_inventory("alice-global", "global", "alice")
        self._add_inventory("bob-private", "private", "bob")
        self.service = UserService(self.db)

    def _add_inventory(self, name: str, scope: str, created_by: str) -> None:
        self.db.add(
            Inventory(name=name, conditions="{}", scope=scope, created_by=created_by)
        )
        self.db.commit()

    def _owners(self) -> dict[str, str]:
        return {i.name: i.created_by for i in self.db.scalars(select(Inventory)).all()}

    def test_rename_carries_private_and_global_inventories(self) -> None:
        self.service.update_user(self.alice.id, username="alicia", actor_user_id=None)
        owners = self._owners()
        self.assertEqual(owners["alice-private"], "alicia")
        self.assertEqual(owners["alice-global"], "alicia")
        self.assertEqual(owners["bob-private"], "bob")

    def test_rename_to_same_name_is_noop(self) -> None:
        with patch.object(InventoryRepository, "reassign_creator") as reassign:
            self.service.update_user(self.alice.id, username="alice", actor_user_id=None)
        reassign.assert_not_called()
        self.assertEqual(self._owners()["alice-private"], "alice")

    def test_delete_removes_private_keeps_global(self) -> None:
        self.assertTrue(self.service.delete_user(self.alice.id, actor_user_id=None))
        owners = self._owners()
        self.assertNotIn("alice-private", owners)
        self.assertEqual(owners["alice-global"], "alice")
        self.assertEqual(owners["bob-private"], "bob")

    def test_new_holder_of_old_name_sees_nothing(self) -> None:
        self.service.update_user(self.alice.id, username="alicia", actor_user_id=None)
        self.db.add(User(username="alice", password_hash="h", is_active=True))
        self.db.commit()
        visible = InventoryRepository(self.db).list_inventories("alice")
        self.assertNotIn("alice-private", {i.name for i in visible})

    def test_deleted_users_name_cannot_be_inherited(self) -> None:
        self.service.delete_user(self.alice.id, actor_user_id=None)
        self.db.add(User(username="alice", password_hash="h", is_active=True))
        self.db.commit()
        visible = InventoryRepository(self.db).list_inventories("alice")
        self.assertNotIn("alice-private", {i.name for i in visible})

    def test_failed_user_update_rolls_back_inventory_reassignment(self) -> None:
        with patch.object(UserRepository, "update_user", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.service.update_user(self.alice.id, username="alicia", actor_user_id=None)
        self.db.rollback()
        self.assertEqual(self._owners()["alice-private"], "alice")


class OrphanDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = _make_session()
        self.addCleanup(self.db.get_bind().dispose)
        self.addCleanup(self.db.close)
        self.db.add(User(username="alice", password_hash="h", is_active=True))
        for name, scope, owner in [
            ("a", "private", "alice"),
            ("g", "global", "ghost-global"),
            ("p", "private", "ghost"),
            ("q", "private", "ghost"),
        ]:
            self.db.add(Inventory(name=name, conditions="{}", scope=scope, created_by=owner))
        self.db.commit()

    def test_list_orphaned_private_creators(self) -> None:
        orphans = InventoryRepository(self.db).list_orphaned_private_creators({"alice"})
        self.assertEqual(orphans, ["ghost"])

    def test_orphan_warning_logged(self) -> None:
        with self.assertLogs("services.users.inventory_orphans", level=logging.WARNING) as logs:
            self.assertEqual(warn_about_orphaned_inventories(self.db), ["ghost"])
        self.assertIn("ghost", logs.output[0])

    def test_no_warning_without_orphans(self) -> None:
        self.db.query(Inventory).filter(Inventory.created_by == "ghost").delete()
        self.db.commit()
        with self.assertNoLogs("services.users.inventory_orphans", level=logging.WARNING):
            self.assertEqual(warn_about_orphaned_inventories(self.db), [])


if __name__ == "__main__":
    unittest.main()
