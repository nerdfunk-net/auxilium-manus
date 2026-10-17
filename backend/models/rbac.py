from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.password_policy import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


class PermissionBase(BaseModel):
    resource: str = Field(..., min_length=1, max_length=100)
    action: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=500)


class PermissionCreate(PermissionBase):
    pass


class Permission(PermissionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class PermissionWithGrant(Permission):
    granted: bool
    source: Literal["role", "override"] | None = None


class RoleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class RoleCreate(RoleBase):
    is_system: bool = False


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class Role(RoleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_system: bool
    created_at: datetime
    updated_at: datetime


class RoleWithPermissions(Role):
    permissions: list[PermissionWithGrant] = Field(default_factory=list)


class UserRoleAssignment(BaseModel):
    user_id: int
    role_id: int


class RolePermissionAssignment(BaseModel):
    # No `granted`: a role-level deny is never evaluated, so it cannot be requested (S2-13).
    # Per-user overrides (UserPermissionAssignment) keep allow and deny.
    model_config = ConfigDict(extra="forbid")

    role_id: int
    permission_id: int


class UserPermissionAssignment(BaseModel):
    user_id: int
    permission_id: int
    granted: bool = True


class UserPermissions(BaseModel):
    user_id: int
    roles: list[str] = Field(default_factory=list)
    permissions: list[PermissionWithGrant] = Field(default_factory=list)
    overrides: list[PermissionWithGrant] = Field(default_factory=list)


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    is_active: bool = True


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(
        default=None, min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
    is_active: bool | None = None


class UserAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    roles: list[str] = Field(default_factory=list)


class UserListResponse(BaseModel):
    users: list[UserAdminResponse]
