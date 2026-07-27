"""Git repository management models."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class GitCategory(StrEnum):
    CONFIGS = "device_configs"
    COCKPIT_CONFIGS = "cockpit_configs"
    TEMPLATES = "templates"
    AGENT = "agent"
    CSV_IMPORTS = "csv_imports"
    CSV_EXPORTS = "csv_exports"


class GitAuthType(StrEnum):
    NONE = "none"
    TOKEN = "token"
    SSH_KEY = "ssh_key"
    GENERIC = "generic"


class GitRepositoryRequest(BaseModel):
    name: str = Field(..., description="Unique repository name")
    category: GitCategory = Field(..., description="Repository category")
    url: str = Field(..., description="Git repository URL")
    branch: str = Field(default="main", description="Default branch")
    auth_type: GitAuthType = Field(default=GitAuthType.TOKEN, description="Authentication type")
    credential_name: str | None = Field(None, description="Name of stored credential")
    path: str | None = Field(None, description="On-disk sub-path override")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    git_author_name: str | None = Field(None, description="Git author name for commits")
    git_author_email: str | None = Field(None, description="Git author email for commits")
    description: str | None = Field(None, description="Repository description")
    is_active: bool = Field(default=True, description="Repository is active")


class GitRepositoryResponse(BaseModel):
    id: int
    name: str
    category: GitCategory
    url: str
    branch: str
    auth_type: str | None = "token"
    credential_name: str | None = None
    path: str | None = None
    verify_ssl: bool
    git_author_name: str | None = None
    git_author_email: str | None = None
    description: str | None = None
    is_active: bool
    created_at: str
    updated_at: str
    last_sync: str | None = None
    sync_status: str | None = None


class GitRepositoryListResponse(BaseModel):
    repositories: list[GitRepositoryResponse]
    total: int


class GitRepositoryUpdateRequest(BaseModel):
    name: str | None = None
    category: GitCategory | None = None
    url: str | None = None
    branch: str | None = None
    auth_type: GitAuthType | None = None
    credential_name: str | None = None
    path: str | None = None
    verify_ssl: bool | None = None
    git_author_name: str | None = None
    git_author_email: str | None = None
    description: str | None = None
    is_active: bool | None = None


class GitConnectionTestRequest(BaseModel):
    url: str
    branch: str = "main"
    auth_type: GitAuthType = GitAuthType.TOKEN
    username: str | None = None
    token: str | None = None
    credential_name: str | None = None
    verify_ssl: bool = True


class GitConnectionTestResponse(BaseModel):
    success: bool
    message: str
    details: dict | None = None


class GitSyncRequest(BaseModel):
    repository_id: int | None = None


class GitSyncResponse(BaseModel):
    synced_repositories: list[int]
    failed_repositories: list[int]
    errors: dict
    message: str
