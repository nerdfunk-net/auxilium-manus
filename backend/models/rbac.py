from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    role_id: int
    permission_id: int
    granted: bool = True


class UserPermissionAssignment(BaseModel):
    user_id: int
    permission_id: int
    granted: bool = True


class PermissionCheck(BaseModel):
    resource: str
    action: str


class PermissionCheckResult(BaseModel):
    has_permission: bool
    resource: str
    action: str
    source: str | None = None


class UserPermissions(BaseModel):
    user_id: int
    roles: list[str] = Field(default_factory=list)
    permissions: list[PermissionWithGrant] = Field(default_factory=list)
    overrides: list[PermissionWithGrant] = Field(default_factory=list)


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)
    is_active: bool = True


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=128)
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
