from __future__ import annotations

from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError
from core.models.rbac import Permission
from repositories.rbac_repository import RBACRepository

ADMIN_ROLE_NAME = "admin"
# Permissions on these resources let a holder change who can do what; only
# admins may hand them out or take them away (policy P3).
PROTECTED_RESOURCES: tuple[str, ...] = ("rbac.", "users", "system.")


def _is_protected(permission: Permission) -> bool:
    return any(
        permission.resource == prefix.rstrip(".") or permission.resource.startswith(prefix)
        for prefix in PROTECTED_RESOURCES
    )


class RBACService:
    def __init__(self, db: Session) -> None:
        self._repo = RBACRepository(db)

    def _require_admin_actor(self, actor_user_id: int | None) -> None:
        if actor_user_id is None:
            return
        if not self.has_role(actor_user_id, "admin"):
            raise AccessDeniedError("Admin role required to modify system roles")

    # ---- policy helpers (P1-P7, see doc/plans/FABE_BACKEND_ISSUES.md §2.2) ----

    def _is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and self.has_role(user_id, ADMIN_ROLE_NAME)

    def assert_not_self(self, actor_user_id: int | None, target_user_id: int) -> None:
        if actor_user_id is not None and actor_user_id == target_user_id:
            raise AccessDeniedError("You cannot change your own roles or permissions")  # P1

    def may_touch_target(self, actor_user_id: int | None, target_user_id: int) -> None:
        if actor_user_id is None or self._is_admin(actor_user_id):
            return
        if self._is_admin(target_user_id):
            raise AccessDeniedError("Admin role required to modify an administrator")  # P4

    def assert_actor_holds(self, actor_user_id: int | None, permissions: list[Permission]) -> None:
        if actor_user_id is None or self._is_admin(actor_user_id):
            return
        for permission in permissions:
            if _is_protected(permission):
                raise AccessDeniedError(
                    f"Admin role required to grant {permission.resource}:{permission.action}"
                )  # P3
            if not self.has_permission(actor_user_id, permission.resource, permission.action):
                raise AccessDeniedError(
                    f"You cannot grant {permission.resource}:{permission.action} "
                    "because you do not hold it"
                )  # P2

    def assert_not_last_admin(self, user_id: int) -> None:
        admin_role = self._repo.get_role_by_name(ADMIN_ROLE_NAME)
        if admin_role is None or not self.has_role(user_id, ADMIN_ROLE_NAME):
            return
        if len(self._repo.get_users_with_role(admin_role.id)) <= 1:
            raise AccessDeniedError("The last administrator cannot be removed")  # P6

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

    def role_has_members(self, role_name: str) -> bool:
        """True if at least one user currently holds the named role."""
        role = self._repo.get_role_by_name(role_name)
        if role is None:
            return False
        return bool(self._repo.get_users_with_role(role.id))

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
    def create_role(
        self,
        name: str,
        description: str | None = None,
        is_system: bool = False,
        *,
        actor_user_id: int | None = None,
    ):
        if is_system:
            self._require_admin_actor(actor_user_id)
        return self._repo.create_role(name, description, is_system)

    def get_role(self, role_id: int):
        return self._repo.get_role(role_id)

    def get_role_by_name(self, name: str):
        return self._repo.get_role_by_name(name)

    def list_roles(self) -> list:
        return self._repo.list_roles()

    def update_role(self, role_id: int, *, name: str | None = None, description: str | None = None):
        role = self.get_role(role_id)
        if role is None:
            return None
        if role.is_system and name is not None and name != role.name:
            raise AccessDeniedError("System roles cannot be renamed")  # P5
        return self._repo.update_role(role_id, name=name, description=description)

    def delete_role(self, role_id: int) -> bool:
        return self._repo.delete_role(role_id)

    def role_name_exists(self, name: str, exclude_role_id: int | None = None) -> bool:
        return self._repo.role_name_exists(name, exclude_role_id)

    # Role <-> Permission
    def assign_permission_to_role(
        self,
        role_id: int,
        permission_id: int,
        granted: bool = True,
        *,
        actor_user_id: int | None = None,
    ):
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
        permission = self._repo.get_permission_by_id(permission_id)
        if permission is not None and granted:
            self.assert_actor_holds(actor_user_id, [permission])  # P2/P3 also for non-system roles
        return self._repo.assign_permission_to_role(role_id, permission_id, granted)

    def remove_permission_from_role(
        self, role_id: int, permission_id: int, *, actor_user_id: int | None = None
    ) -> bool:
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
        return self._repo.remove_permission_from_role(role_id, permission_id)

    def get_role_permissions(self, role_id: int) -> list[Permission]:
        return self._repo.get_role_permissions(role_id)

    # User <-> Role
    def assign_role_to_user(self, user_id: int, role_id: int, *, actor_user_id: int | None = None):
        self.assert_not_self(actor_user_id, user_id)  # P1
        self.may_touch_target(actor_user_id, user_id)  # P4
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
        elif role is not None:
            self.assert_actor_holds(actor_user_id, self._repo.get_role_permissions(role.id))  # P2
        return self._repo.assign_role_to_user(user_id, role_id)

    def remove_role_from_user(
        self, user_id: int, role_id: int, *, actor_user_id: int | None = None
    ) -> bool:
        self.assert_not_self(actor_user_id, user_id)  # P1
        self.may_touch_target(actor_user_id, user_id)  # P4
        role = self.get_role(role_id)
        if role is not None and role.is_system:
            self._require_admin_actor(actor_user_id)
            if role.name == ADMIN_ROLE_NAME:
                self.assert_not_last_admin(user_id)  # P6
        return self._repo.remove_role_from_user(user_id, role_id)

    def get_users_with_role(self, role_id: int) -> list:
        return self._repo.get_users_with_role(role_id)

    # User <-> Permission overrides
    def assign_permission_to_user(
        self,
        user_id: int,
        permission_id: int,
        granted: bool = True,
        *,
        actor_user_id: int | None = None,
    ):
        self.assert_not_self(actor_user_id, user_id)  # P1
        self.may_touch_target(actor_user_id, user_id)  # P4
        permission = self._repo.get_permission_by_id(permission_id)
        if permission is not None:
            if granted:
                self.assert_actor_holds(actor_user_id, [permission])  # P2/P3
            elif _is_protected(permission):
                # A deny-override on a protected permission is as dangerous as an allow.
                self._require_admin_actor(actor_user_id)
        return self._repo.assign_permission_to_user(user_id, permission_id, granted)

    def remove_permission_from_user(
        self, user_id: int, permission_id: int, *, actor_user_id: int | None = None
    ) -> bool:
        self.assert_not_self(actor_user_id, user_id)  # P1
        self.may_touch_target(actor_user_id, user_id)  # P4
        return self._repo.remove_permission_from_user(user_id, permission_id)

    def get_user_permission_overrides_with_status(
        self,
        user_id: int,
    ) -> list[tuple[Permission, bool]]:
        return self._repo.get_user_permission_overrides_with_status(user_id)
