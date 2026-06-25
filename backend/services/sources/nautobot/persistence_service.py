"""
Inventory persistence service — PostgreSQL CRUD for saved inventory configurations.

Replaces the root-level inventory_manager.py singleton. Receives the repository
via constructor injection so callers (routers, services, tasks) obtain an instance
through service_factory.build_inventory_service() or
dependencies.get_inventory_service().

See: doc/refactoring/REFACTORING_INVENTORY.md — Step 3
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.models.inventories import Inventory
from repositories.inventory_repository import InventoryRepository

logger = logging.getLogger(__name__)


class InventoryService:
    """Manages Ansible inventory configurations in PostgreSQL database."""

    def __init__(self, repository: InventoryRepository):
        self.repository = repository

    # ------------------------------------------------------------------
    # Access control
    # ------------------------------------------------------------------

    def _assert_access(self, inventory: dict, username: str) -> None:
        """Raise PermissionError if user cannot access a private inventory."""
        if inventory.get("scope") == "private" and inventory.get("created_by") != username:
            raise PermissionError(f"Access denied to inventory {inventory['id']}")

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create_inventory(self, inventory_data: dict[str, Any]) -> int | None:
        """Create a new inventory."""
        try:
            if not inventory_data.get("name"):
                raise ValueError("Inventory name is required")

            if not inventory_data.get("created_by"):
                raise ValueError("Creator username is required")

            if not inventory_data.get("conditions"):
                raise ValueError("Conditions are required")

            # Check for existing active inventory with same name and creator
            existing = self.repository.get_by_name(
                inventory_data["name"], inventory_data["created_by"], active_only=True
            )
            if existing:
                raise ValueError(
                    f"Inventory with name '{inventory_data['name']}' already exists for this user"
                )

            conditions_json = json.dumps(inventory_data["conditions"])

            inventory = self.repository.create(
                name=inventory_data["name"],
                description=inventory_data.get("description"),
                conditions=conditions_json,
                template_category=inventory_data.get("template_category"),
                template_name=inventory_data.get("template_name"),
                scope=inventory_data.get("scope", "global"),
                group_path=inventory_data.get("group_path") or None,
                created_by=inventory_data["created_by"],
                is_active=True,
            )

            logger.info(
                "Inventory '%s' created with ID %s by %s",
                inventory_data["name"],
                inventory.id,
                inventory_data["created_by"],
            )
            return inventory.id

        except ValueError:
            raise
        except Exception as e:
            logger.error("Error creating inventory: %s", e)
            raise

    def get_inventory(
        self,
        inventory_id: int,
        username: str | None = None,
    ) -> dict[str, Any] | None:
        """Get an inventory by ID.

        If *username* is provided, raises PermissionError when the caller
        does not have access to a private inventory.
        """
        try:
            inventory = self.repository.get_by_id(inventory_id)
            if not inventory:
                return None

            result = self._model_to_dict(inventory)

            if username is not None:
                self._assert_access(result, username)

            return result

        except PermissionError:
            raise
        except Exception as e:
            logger.error("Error getting inventory %s: %s", inventory_id, e)
            return None

    def get_inventory_by_name(self, name: str, username: str) -> dict[str, Any] | None:
        """Get an inventory by name for a specific user."""
        try:
            inventory = self.repository.get_by_name(name, username, active_only=True)
            if inventory:
                return self._model_to_dict(inventory)
            return None

        except Exception as e:
            logger.error("Error getting inventory by name '%s': %s", name, e)
            return None

    def list_inventories(
        self,
        username: str,
        active_only: bool = True,
        scope: str | None = None,
        group_path_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """List inventories accessible to a user.

        Returns global inventories and private inventories owned by the user.
        """
        try:
            inventories = self.repository.list_inventories(
                username=username,
                active_only=active_only,
                scope=scope,
                group_path_filter=group_path_filter,
            )

            results = [self._model_to_dict(inv) for inv in inventories]
            logger.info(
                "Listed %s inventories for user %s (scope=%s, group_path_filter=%s)",
                len(results),
                username,
                scope,
                group_path_filter,
            )
            return results

        except Exception as e:
            logger.error("Error listing inventories: %s", e)
            return []

    def get_all_groups(self, username: str) -> list[str]:
        """Return all unique group paths (including ancestor paths) accessible to a user.

        For example, if inventories use 'networking/dc1' and 'security', this returns
        ['networking', 'networking/dc1', 'security'].
        """
        try:
            raw_paths = self.repository.get_distinct_group_paths(username)

            all_paths: set[str] = set()
            for path in raw_paths:
                segments = path.split("/")
                for i in range(1, len(segments) + 1):
                    all_paths.add("/".join(segments[:i]))

            return sorted(all_paths)

        except Exception as e:
            logger.error("Error fetching inventory groups: %s", e)
            return []

    def rename_group(self, old_path: str, new_name: str, username: str) -> dict:
        """Rename the last segment of old_path to new_name across all matching inventories.

        Args:
            old_path: Full path of the group to rename (e.g. 'networking/dc1')
            new_name: New leaf segment name (e.g. 'datacenter1')
            username: Authenticated user performing the rename

        Returns:
            Dict with 'updated_count' and 'new_path'

        Raises:
            ValueError: If old_path is empty, new_name is empty, or new_name contains '/'
        """
        if not old_path:
            raise ValueError("Cannot rename the root group")
        if not new_name or not new_name.strip():
            raise ValueError("New group name must not be empty")
        if "/" in new_name:
            raise ValueError("Group name must not contain '/'")

        new_name = new_name.strip()
        segments = old_path.split("/")
        segments[-1] = new_name
        new_path = "/".join(segments)

        if new_path == old_path:
            logger.info("rename_group: old_path == new_path ('%s'), skipping update", old_path)
            return {"updated_count": 0, "new_path": new_path}

        try:
            updated_count = self.repository.rename_group(old_path, new_path, username)
            logger.info(
                "Renamed group '%s' -> '%s': %s rows updated by %s",
                old_path,
                new_path,
                updated_count,
                username,
            )
            return {"updated_count": updated_count, "new_path": new_path}
        except Exception as e:
            logger.error("Error renaming group '%s': %s", old_path, e)
            raise

    def update_inventory(
        self, inventory_id: int, inventory_data: dict[str, Any], username: str
    ) -> bool:
        """Update an existing inventory."""
        try:
            current_obj = self.repository.get_by_id(inventory_id)
            if not current_obj:
                raise ValueError(f"Inventory with ID {inventory_id} not found")

            if current_obj.scope == "private" and current_obj.created_by != username:
                raise ValueError("You don't have permission to update this inventory")

            current = self._model_to_dict(current_obj)

            conditions_json = (
                json.dumps(inventory_data["conditions"])
                if "conditions" in inventory_data
                else current_obj.conditions
            )

            update_kwargs = {
                "name": inventory_data.get("name", current["name"]),
                "description": inventory_data.get("description", current["description"]),
                "conditions": conditions_json,
                "template_category": inventory_data.get(
                    "template_category", current["template_category"]
                ),
                "template_name": inventory_data.get("template_name", current["template_name"]),
                "scope": inventory_data.get("scope", current["scope"]),
                "group_path": inventory_data.get("group_path", current.get("group_path")) or None,
            }

            self.repository.update(inventory_id, **update_kwargs)
            logger.info("Inventory %s updated by %s", inventory_id, username)
            return True

        except Exception as e:
            logger.error("Error updating inventory %s: %s", inventory_id, e)
            raise

    def delete_inventory(self, inventory_id: int, username: str, hard_delete: bool = True) -> bool:
        """Delete an inventory (hard delete by default)."""
        try:
            inventory = self.repository.get_by_id(inventory_id)
            if not inventory:
                raise ValueError(f"Inventory with ID {inventory_id} not found")

            if inventory.scope == "private" and inventory.created_by != username:
                raise ValueError("You don't have permission to delete this inventory")

            if hard_delete:
                self.repository.delete(inventory_id)
            else:
                self.repository.update(inventory_id, is_active=False)

            logger.info(
                "Inventory %s %s by %s",
                inventory_id,
                "deleted" if hard_delete else "deactivated",
                username,
            )
            return True

        except Exception as e:
            logger.error("Error deleting inventory %s: %s", inventory_id, e)
            raise

    def delete_inventory_by_name(self, name: str, username: str, hard_delete: bool = True) -> bool:
        """Delete an inventory by name (hard delete by default)."""
        try:
            inventory = self.repository.get_by_name(name, username, active_only=False)
            if not inventory:
                raise ValueError(f"Inventory '{name}' not found")

            return self.delete_inventory(inventory.id, username, hard_delete)

        except Exception as e:
            logger.error("Error deleting inventory by name '%s': %s", name, e)
            raise

    def search_inventories(
        self, query: str, username: str, active_only: bool = True
    ) -> list[dict[str, Any]]:
        """Search inventories by name or description."""
        try:
            inventories = self.repository.search_inventories(query, username, active_only)
            return [self._model_to_dict(inv) for inv in inventories]

        except Exception as e:
            logger.error("Error searching inventories: %s", e)
            return []

    def health_check(self) -> dict[str, Any]:
        """Check inventory database health."""
        try:
            active_count = self.repository.get_active_count()
            total_count = self.repository.get_total_count()
            return {
                "status": "healthy",
                "storage_type": "database",
                "active_inventories": active_count,
                "total_inventories": total_count,
            }
        except Exception as e:
            logger.error("Inventory database health check failed: %s", e)
            return {"status": "unhealthy", "error": str(e)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _model_to_dict(self, inventory: Inventory) -> dict[str, Any]:
        """Convert SQLAlchemy model to dictionary."""
        result = {
            "id": inventory.id,
            "name": inventory.name,
            "description": inventory.description,
            "template_category": inventory.template_category,
            "template_name": inventory.template_name,
            "scope": inventory.scope,
            "group_path": inventory.group_path,
            "created_by": inventory.created_by,
            "is_active": bool(inventory.is_active),
            "created_at": (inventory.created_at.isoformat() if inventory.created_at else None),
            "updated_at": (inventory.updated_at.isoformat() if inventory.updated_at else None),
        }

        if inventory.conditions:
            try:
                result["conditions"] = json.loads(inventory.conditions)
            except json.JSONDecodeError:
                logger.error("Failed to parse conditions for inventory %s", inventory.id)
                result["conditions"] = []
        else:
            result["conditions"] = []

        return result
