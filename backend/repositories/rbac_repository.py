from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.rbac import Permission, Role, RolePermission, UserPermission, UserRole
from core.models.users import User


class RBACRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # Permissions
    def create_permission(
        self,
        resource: str,
        action: str,
        description: str | None = None,
    ) -> Permission:
        permission = Permission(resource=resource, action=action, description=description)
        self.db.add(permission)
        self.db.commit()
        self.db.refresh(permission)
        return permission

    def get_permission(self, resource: str, action: str) -> Permission | None:
        return self.db.scalar(
            select(Permission).where(
                Permission.resource == resource,
                Permission.action == action,
            ),
        )

    def get_permission_by_id(self, permission_id: int) -> Permission | None:
        return self.db.get(Permission, permission_id)

    def list_permissions(self) -> list[Permission]:
        query = select(Permission).order_by(Permission.resource, Permission.action)
        return list(self.db.scalars(query))

    def delete_permission(self, permission_id: int) -> bool:
        permission = self.db.get(Permission, permission_id)
        if permission is None:
            return False
        self.db.delete(permission)
        self.db.commit()
        return True

    # Roles
    def create_role(
        self,
        name: str,
        description: str | None = None,
        is_system: bool = False,
    ) -> Role:
        role = Role(name=name, description=description, is_system=is_system)
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def get_role(self, role_id: int) -> Role | None:
        return self.db.get(Role, role_id)

    def get_role_by_name(self, name: str) -> Role | None:
        return self.db.scalar(select(Role).where(Role.name == name))

    def list_roles(self) -> list[Role]:
        return list(self.db.scalars(select(Role).order_by(Role.name)))

    def update_role(self, role_id: int, **kwargs: object) -> Role | None:
        role = self.db.get(Role, role_id)
        if role is None:
            return None
        for key, value in kwargs.items():
            if value is not None and hasattr(role, key):
                setattr(role, key, value)
        self.db.commit()
        self.db.refresh(role)
        return role

    def delete_role(self, role_id: int) -> bool:
        role = self.db.get(Role, role_id)
        if role is None:
            return False
        self.db.delete(role)
        self.db.commit()
        return True

    def role_name_exists(self, name: str, exclude_role_id: int | None = None) -> bool:
        query = select(Role.id).where(Role.name == name)
        if exclude_role_id is not None:
            query = query.where(Role.id != exclude_role_id)
        return self.db.scalar(query) is not None

    # Role <-> Permission
    def assign_permission_to_role(
        self,
        role_id: int,
        permission_id: int,
        granted: bool = True,
    ) -> RolePermission:
        existing = self.db.get(RolePermission, (role_id, permission_id))
        if existing is not None:
            existing.granted = granted
            self.db.commit()
            self.db.refresh(existing)
            return existing

        role_permission = RolePermission(
            role_id=role_id,
            permission_id=permission_id,
            granted=granted,
        )
        self.db.add(role_permission)
        self.db.commit()
        self.db.refresh(role_permission)
        return role_permission

    def remove_permission_from_role(self, role_id: int, permission_id: int) -> bool:
        role_permission = self.db.get(RolePermission, (role_id, permission_id))
        if role_permission is None:
            return False
        self.db.delete(role_permission)
        self.db.commit()
        return True

    def get_role_permissions(self, role_id: int) -> list[Permission]:
        return list(
            self.db.scalars(
                select(Permission)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role_id, RolePermission.granted == True),  # noqa: E712
            ),
        )

    # User <-> Role
    def assign_role_to_user(self, user_id: int, role_id: int) -> UserRole:
        existing = self.db.get(UserRole, (user_id, role_id))
        if existing is not None:
            return existing

        user_role = UserRole(user_id=user_id, role_id=role_id)
        self.db.add(user_role)
        self.db.commit()
        self.db.refresh(user_role)
        return user_role

    def remove_role_from_user(self, user_id: int, role_id: int) -> bool:
        user_role = self.db.get(UserRole, (user_id, role_id))
        if user_role is None:
            return False
        self.db.delete(user_role)
        self.db.commit()
        return True

    def get_user_roles(self, user_id: int) -> list[Role]:
        return list(
            self.db.scalars(
                select(Role)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user_id),
            ),
        )

    def get_users_with_role(self, role_id: int) -> list[User]:
        return list(
            self.db.scalars(
                select(User)
                .join(UserRole, UserRole.user_id == User.id)
                .where(UserRole.role_id == role_id),
            ),
        )

    # User <-> Permission overrides
    def assign_permission_to_user(
        self,
        user_id: int,
        permission_id: int,
        granted: bool = True,
    ) -> UserPermission:
        existing = self.db.get(UserPermission, (user_id, permission_id))
        if existing is not None:
            existing.granted = granted
            self.db.commit()
            self.db.refresh(existing)
            return existing

        user_permission = UserPermission(
            user_id=user_id,
            permission_id=permission_id,
            granted=granted,
        )
        self.db.add(user_permission)
        self.db.commit()
        self.db.refresh(user_permission)
        return user_permission

    def remove_permission_from_user(self, user_id: int, permission_id: int) -> bool:
        user_permission = self.db.get(UserPermission, (user_id, permission_id))
        if user_permission is None:
            return False
        self.db.delete(user_permission)
        self.db.commit()
        return True

    def get_user_permissions(self, user_id: int) -> list[Permission]:
        return list(
            self.db.scalars(
                select(Permission)
                .join(UserPermission, UserPermission.permission_id == Permission.id)
                .where(UserPermission.user_id == user_id, UserPermission.granted == True),  # noqa: E712
            ),
        )

    def get_user_permission_override(self, user_id: int, permission_id: int) -> bool | None:
        user_permission = self.db.get(UserPermission, (user_id, permission_id))
        if user_permission is None:
            return None
        return user_permission.granted

    def get_user_permission_overrides_with_status(
        self,
        user_id: int,
    ) -> list[tuple[Permission, bool]]:
        rows = self.db.execute(
            select(Permission, UserPermission.granted)
            .join(UserPermission, UserPermission.permission_id == Permission.id)
            .where(UserPermission.user_id == user_id),
        )
        return [(permission, granted) for permission, granted in rows]
