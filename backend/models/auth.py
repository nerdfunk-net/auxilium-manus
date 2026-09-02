from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from services.auth.password_policy import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(..., min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool
    must_change_password: bool = False
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserResponse


class OIDCProvider(BaseModel):
    provider_id: str
    name: str
    description: str | None = None
    icon: str | None = None
    display_order: int = 999


class OIDCProvidersResponse(BaseModel):
    providers: list[OIDCProvider] = Field(default_factory=list)
    allow_traditional_login: bool = True


class OIDCLoginResponse(BaseModel):
    authorization_url: str
    state: str
    provider_id: str


class OIDCCallbackRequest(BaseModel):
    code: str = Field(..., min_length=1)
    state: str | None = None
    redirect_uri: str | None = None


class OIDCTestLoginRequest(BaseModel):
    redirect_uri: str | None = None
    scopes: list[str] | None = None
    response_type: str | None = None
    client_id: str | None = None


class OIDCLogoutResponse(BaseModel):
    logout_url: str | None = None
    requires_redirect: bool = False


class ApprovalPendingResponse(BaseModel):
    status: Literal["approval_pending"] = "approval_pending"
    username: str
    email: str | None = None
    oidc_provider: str
