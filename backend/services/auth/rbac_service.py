from __future__ import annotations

from sqlalchemy.orm import Session

from core.models.rbac import Permission
from repositories.rbac_repository import RBACRepository


class RBACService:
    def __init__(self, db: Session) -> None:
        self._repo = RBACRepository(db)

    def has_permission(self, user_id: int, resource: str, action: str) -> bool:
        permission = self._repo.get_permission(resource, action)
        if permission is None:
            return False

        override = self._repo.get_user_permission_override(user_id, permission.id)
        if override is not None:
            return override

        for role in self._repo.get_user_roles(user_id):
            if any(p.id == permission.id for p in self._repo.get_role_permissions(role.id)):
                return True

        return False

    def check_any_permission(self, user_id: int, checks: list[tuple[str, str]]) -> bool:
        return any(self.has_permission(user_id, resource, action) for resource, action in checks)

    def check_all_permissions(self, user_id: int, checks: list[tuple[str, str]]) -> bool:
        return all(self.has_permission(user_id, resource, action) for resource, action in checks)

    def has_role(self, user_id: int, role_name: str) -> bool:
        return any(role.name == role_name for role in self._repo.get_user_roles(user_id))

    def get_user_roles(self, user_id: int) -> list[str]:
        return [role.name for role in self._repo.get_user_roles(user_id)]

    def get_effective_permissions(self, user_id: int) -> list[tuple[Permission, str]]:
        """Merged, deduped currently-granted permissions as (Permission, source) pairs."""
        merged: dict[tuple[str, str], tuple[Permission, str]] = {}

        for role in self._repo.get_user_roles(user_id):
            for permission in self._repo.get_role_permissions(role.id):
                merged[(permission.resource, permission.action)] = (permission, "role")

        for permission, granted in self._repo.get_user_permission_overrides_with_status(user_id):
            key = (permission.resource, permission.action)
            if granted:
                merged[key] = (permission, "override")
            else:
                merged.pop(key, None)

        return [merged[key] for key in sorted(merged)]

    def get_user_permission_strings(self, user_id: int) -> list[str]:
        """Merged role- and override-granted permissions as 'resource:action' strings."""
        return [
            f"{permission.resource}:{permission.action}"
            for permission, _source in self.get_effective_permissions(user_id)
        ]

    def assign_role_to_user_by_name(self, user_id: int, role_name: str) -> None:
        role = self._repo.get_role_by_name(role_name)
        if role is None:
            return
        self._repo.assign_role_to_user(user_id, role.id)

    # Permissions CRUD passthroughs
    def create_permission(
        self,
        resource: str,
        action: str,
        description: str | None = None,
    ) -> Permission:
        return self._repo.create_permission(resource, action, description)

    def get_permission_by_id(self, permission_id: int) -> Permission | None:
        return self._repo.get_permission_by_id(permission_id)

    def list_permissions(self) -> list[Permission]:
        return self._repo.list_permissions()

    def delete_permission(self, permission_id: int) -> bool:
        return self._repo.delete_permission(permission_id)

    # Roles CRUD passthroughs
    def create_role(self, name: str, description: str | None = None, is_system: bool = False):
        return self._repo.create_role(name, description, is_system)

    def get_role(self, role_id: int):
        return self._repo.get_role(role_id)

    def get_role_by_name(self, name: str):
        return self._repo.get_role_by_name(name)

    def list_roles(self) -> list:
        return self._repo.list_roles()

    def update_role(self, role_id: int, **kwargs: object):
        return self._repo.update_role(role_id, **kwargs)

    def delete_role(self, role_id: int) -> bool:
        return self._repo.delete_role(role_id)

    def role_name_exists(self, name: str, exclude_role_id: int | None = None) -> bool:
        return self._repo.role_name_exists(name, exclude_role_id)

    # Role <-> Permission
    def assign_permission_to_role(self, role_id: int, permission_id: int, granted: bool = True):
        return self._repo.assign_permission_to_role(role_id, permission_id, granted)

    def remove_permission_from_role(self, role_id: int, permission_id: int) -> bool:
        return self._repo.remove_permission_from_role(role_id, permission_id)

    def get_role_permissions(self, role_id: int) -> list[Permission]:
        return self._repo.get_role_permissions(role_id)

    # User <-> Role
    def assign_role_to_user(self, user_id: int, role_id: int):
        return self._repo.assign_role_to_user(user_id, role_id)

    def remove_role_from_user(self, user_id: int, role_id: int) -> bool:
        return self._repo.remove_role_from_user(user_id, role_id)

    def get_users_with_role(self, role_id: int) -> list:
        return self._repo.get_users_with_role(role_id)

    # User <-> Permission overrides
    def assign_permission_to_user(self, user_id: int, permission_id: int, granted: bool = True):
        return self._repo.assign_permission_to_user(user_id, permission_id, granted)

    def remove_permission_from_user(self, user_id: int, permission_id: int) -> bool:
        return self._repo.remove_permission_from_user(user_id, permission_id)

    def get_user_permission_overrides_with_status(
        self,
        user_id: int,
    ) -> list[tuple[Permission, bool]]:
        return self._repo.get_user_permission_overrides_with_status(user_id)
