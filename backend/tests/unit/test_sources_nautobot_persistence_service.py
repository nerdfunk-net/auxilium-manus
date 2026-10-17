"""CRUD tests for services/sources/nautobot/persistence_service.py + inventory_repository.

Exercises InventoryService against a real in-memory SQLite database, which also
covers repositories/inventory_repository.py.
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models.inventories import Inventory
from repositories.inventory_repository import InventoryRepository
from services.sources.nautobot.persistence_service import InventoryService

_USER = "alice"


class InventoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Inventory.metadata.create_all(engine, tables=[Inventory.__table__])
        self.addCleanup(engine.dispose)
        self.db = sessionmaker(bind=engine)()
        self.addCleanup(self.db.close)
        self.service = InventoryService(InventoryRepository(self.db))

    def _create(self, **over) -> int:
        data = {
            "name": "inv1",
            "created_by": _USER,
            "conditions": [{"version": 2, "tree": {}}],
            "scope": "global",
        }
        data.update(over)
        return self.service.create_inventory(data)

    # -- create ---------------------------------------------------------
    def test_create_requires_name_and_creator(self) -> None:
        with self.assertRaises(ValueError):
            self.service.create_inventory({"created_by": _USER, "conditions": [1]})
        with self.assertRaises(ValueError):
            self.service.create_inventory({"name": "x", "conditions": [1]})

    def test_create_filter_requires_conditions(self) -> None:
        with self.assertRaises(ValueError):
            self.service.create_inventory({"name": "x", "created_by": _USER, "conditions": []})

    def test_create_static_requires_device_ids(self) -> None:
        with self.assertRaises(ValueError):
            self.service.create_inventory(
                {"name": "x", "created_by": _USER, "inventory_type": "static", "device_ids": []}
            )

    def test_create_static_ok(self) -> None:
        inv_id = self._create(inventory_type="static", device_ids=["d1", "d2"], conditions=[])
        stored = self.service.get_inventory(inv_id)
        self.assertEqual(stored["inventory_type"], "static")
        self.assertEqual(stored["device_ids"], ["d1", "d2"])

    def test_create_rejects_duplicate_name_for_same_user(self) -> None:
        self._create()
        with self.assertRaises(ValueError):
            self._create()

    # -- read ---------------------------------------------------------
    def test_get_inventory_missing_returns_none(self) -> None:
        self.assertIsNone(self.service.get_inventory(999))

    def test_get_inventory_private_access_control(self) -> None:
        inv_id = self._create(name="secret", scope="private")
        self.assertIsNotNone(self.service.get_inventory(inv_id, username=_USER))
        with self.assertRaises(PermissionError):
            self.service.get_inventory(inv_id, username="mallory")

    def test_get_inventory_by_name(self) -> None:
        self._create(name="findme")
        self.assertEqual(self.service.get_inventory_by_name("findme", _USER)["name"], "findme")
        self.assertIsNone(self.service.get_inventory_by_name("nope", _USER))

    def test_list_inventories_scopes(self) -> None:
        self._create(name="g1", scope="global")
        self._create(name="p1", scope="private")
        self._create(name="p2-other", scope="private", created_by="bob")
        mine = self.service.list_inventories(_USER)
        self.assertEqual({i["name"] for i in mine}, {"g1", "p1"})
        self.assertEqual(
            [i["name"] for i in self.service.list_inventories(_USER, scope="global")], ["g1"]
        )

    def test_search_inventories(self) -> None:
        self._create(name="prod-switches", description="datacenter")
        self._create(name="lab", description="test bench")
        hits = self.service.search_inventories("datacenter", _USER)
        self.assertEqual([i["name"] for i in hits], ["prod-switches"])

    # -- groups -----------------------------------------------------
    def test_get_all_groups_expands_ancestors(self) -> None:
        self._create(name="a", group_path="networking/dc1")
        self._create(name="b", group_path="security")
        self.assertEqual(
            self.service.get_all_groups(_USER), ["networking", "networking/dc1", "security"]
        )

    def test_rename_group_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.service.rename_group("", "x", _USER)
        with self.assertRaises(ValueError):
            self.service.rename_group("a/b", "  ", _USER)
        with self.assertRaises(ValueError):
            self.service.rename_group("a/b", "c/d", _USER)

    def test_rename_group_noop_when_unchanged(self) -> None:
        out = self.service.rename_group("a/b", "b", _USER)
        self.assertEqual(out, {"updated_count": 0, "new_path": "a/b"})

    def test_rename_group_updates_matching_rows(self) -> None:
        self._create(name="a", group_path="net/dc1")
        self._create(name="b", group_path="net/dc1/rack1")
        out = self.service.rename_group("net/dc1", "datacenter", _USER)
        self.assertEqual(out["new_path"], "net/datacenter")
        self.assertEqual(out["updated_count"], 2)
        paths = {i["group_path"] for i in self.service.list_inventories(_USER)}
        self.assertEqual(paths, {"net/datacenter", "net/datacenter/rack1"})

    # -- update / delete -------------------------------------------
    def test_update_inventory_changes_fields(self) -> None:
        inv_id = self._create()
        self.assertTrue(
            self.service.update_inventory(
                inv_id, {"name": "renamed", "conditions": [{"version": 2, "tree": {"x": 1}}]}, _USER
            )
        )
        stored = self.service.get_inventory(inv_id)
        self.assertEqual(stored["name"], "renamed")
        self.assertEqual(stored["conditions"], [{"version": 2, "tree": {"x": 1}}])

    def test_update_inventory_missing_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.service.update_inventory(999, {"name": "x"}, _USER)

    def test_update_inventory_permission_denied(self) -> None:
        inv_id = self._create(name="secret", scope="private")
        with self.assertRaises(ValueError):
            self.service.update_inventory(inv_id, {"name": "x"}, "mallory")

    def test_delete_inventory_hard_and_soft(self) -> None:
        hard_id = self._create(name="h")
        self.assertTrue(self.service.delete_inventory(hard_id, _USER))
        self.assertIsNone(self.service.get_inventory(hard_id))

        soft_id = self._create(name="s")
        self.assertTrue(self.service.delete_inventory(soft_id, _USER, hard_delete=False))
        self.assertFalse(self.service.get_inventory(soft_id)["is_active"])

    def test_delete_inventory_by_name(self) -> None:
        self._create(name="byname")
        self.assertTrue(self.service.delete_inventory_by_name("byname", _USER))
        with self.assertRaises(ValueError):
            self.service.delete_inventory_by_name("byname", _USER)

    def test_health_check(self) -> None:
        self._create(name="a")
        self._create(name="b")
        self.service.delete_inventory(self._create(name="c"), _USER, hard_delete=False)
        health = self.service.health_check()
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["total_inventories"], 3)
        self.assertEqual(health["active_inventories"], 2)

    def test_model_to_dict_handles_bad_conditions_json(self) -> None:
        inv_id = self._create()
        obj = self.db.get(Inventory, inv_id)
        obj.conditions = "{not valid json"
        self.db.commit()
        self.assertEqual(self.service.get_inventory(inv_id)["conditions"], [])


if __name__ == "__main__":
    unittest.main()
