"""Git repository management models."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class GitCategory(str, Enum):
    CONFIGS = "device_configs"
    COCKPIT_CONFIGS = "cockpit_configs"
    TEMPLATES = "templates"
    AGENT = "agent"
    CSV_IMPORTS = "csv_imports"
    CSV_EXPORTS = "csv_exports"


class GitAuthType(str, Enum):
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
    credential_name: Optional[str] = Field(None, description="Name of stored credential")
    path: Optional[str] = Field(None, description="On-disk sub-path override")
    verify_ssl: bool = Field(default=True, description="Verify SSL certificates")
    git_author_name: Optional[str] = Field(None, description="Git author name for commits")
    git_author_email: Optional[str] = Field(None, description="Git author email for commits")
    description: Optional[str] = Field(None, description="Repository description")
    is_active: bool = Field(default=True, description="Repository is active")


class GitRepositoryResponse(BaseModel):
    id: int
    name: str
    category: GitCategory
    url: str
    branch: str
    auth_type: Optional[str] = "token"
    credential_name: Optional[str] = None
    path: Optional[str] = None
    verify_ssl: bool
    git_author_name: Optional[str] = None
    git_author_email: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    created_at: str
    updated_at: str
    last_sync: Optional[str] = None
    sync_status: Optional[str] = None


class GitRepositoryListResponse(BaseModel):
    repositories: List[GitRepositoryResponse]
    total: int


class GitRepositoryUpdateRequest(BaseModel):
    name: Optional[str] = None
    category: Optional[GitCategory] = None
    url: Optional[str] = None
    branch: Optional[str] = None
    auth_type: Optional[GitAuthType] = None
    credential_name: Optional[str] = None
    path: Optional[str] = None
    verify_ssl: Optional[bool] = None
    git_author_name: Optional[str] = None
    git_author_email: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class GitConnectionTestRequest(BaseModel):
    url: str
    branch: str = "main"
    auth_type: GitAuthType = GitAuthType.TOKEN
    username: Optional[str] = None
    token: Optional[str] = None
    credential_name: Optional[str] = None
    verify_ssl: bool = True


class GitConnectionTestResponse(BaseModel):
    success: bool
    message: str
    details: Optional[dict] = None


class GitSyncRequest(BaseModel):
    repository_id: Optional[int] = None


class GitSyncResponse(BaseModel):
    synced_repositories: List[int]
    failed_repositories: List[int]
    errors: dict
    message: str
