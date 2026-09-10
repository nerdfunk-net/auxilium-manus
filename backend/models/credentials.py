from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.passphrase_cipher import normalize_algorithm

CredentialType = Literal["ssh", "ssh_key", "tacacs", "generic", "token", "shared_secret"]
CredentialStatus = Literal["active", "expiring", "expired", "unknown"]
CredentialVisibility = Literal["global", "private"]
CredentialStorageBackend = Literal["local", "vault"]
ALLOWED_CREDENTIAL_TYPES = frozenset(
    {"ssh", "ssh_key", "tacacs", "generic", "token", "shared_secret"}
)


def _validate_algorithm(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_algorithm(value)


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    type: CredentialType = "ssh"
    password: str | None = None
    ssh_private_key: str | None = None
    ssh_passphrase: str | None = None
    algorithm: str | None = None
    valid_until: date | None = None
    visibility: CredentialVisibility = "private"
    # "local" (default, encrypted in Postgres) or "vault" (written to OpenBao by
    # the backend). The secret value still arrives in `password` / `ssh_private_key`.
    storage_backend: CredentialStorageBackend = "local"

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in ALLOWED_CREDENTIAL_TYPES:
            raise ValueError("Invalid credential type")
        return value

    @field_validator("algorithm")
    @classmethod
    def validate_algorithm(cls, value: str | None) -> str | None:
        return _validate_algorithm(value)

    @model_validator(mode="after")
    def validate_credential_data(self) -> CredentialCreate:
        if self.type == "ssh_key":
            if not self.ssh_private_key:
                raise ValueError("SSH private key is required for ssh_key type")
        elif not self.password:
            raise ValueError("Password is required for non-ssh_key types")
        if self.type == "shared_secret":
            # The passphrase rides in `password`; default the algorithm.
            self.algorithm = normalize_algorithm(self.algorithm)
        return self


class CredentialUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    username: str | None = Field(default=None, min_length=1, max_length=128)
    type: CredentialType | None = None
    password: str | None = None
    ssh_private_key: str | None = None
    ssh_passphrase: str | None = None
    algorithm: str | None = None
    valid_until: date | None = None
    visibility: CredentialVisibility | None = None
    # Reserved for the future local <-> vault move action. The service currently
    # rejects a value that differs from the credential's current backend (422).
    storage_backend: CredentialStorageBackend | None = None

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str | None) -> str | None:
        if value is not None and value not in ALLOWED_CREDENTIAL_TYPES:
            raise ValueError("Invalid credential type")
        return value

    @field_validator("algorithm")
    @classmethod
    def validate_algorithm(cls, value: str | None) -> str | None:
        return _validate_algorithm(value)


class CredentialResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    username: str
    type: str
    algorithm: str | None = None
    valid_until: str | None
    is_active: bool
    source: str
    owner: str | None
    owner_user_id: int | None
    owner_username: str | None
    visibility: CredentialVisibility
    storage_backend: CredentialStorageBackend = "local"
    vault_path: str | None = None
    created_at: datetime | None
    updated_at: datetime | None
    status: CredentialStatus
    has_password: bool
    has_ssh_key: bool
    has_ssh_passphrase: bool


class CredentialListResponse(BaseModel):
    credentials: list[CredentialResponse]


class CredentialPasswordResponse(BaseModel):
    password: str
