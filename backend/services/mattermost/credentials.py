"""Per-request Mattermost connection settings and bearer token."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MattermostCredentials:
    base_url: str
    token: str
    timeout: float = 30.0
    verify_ssl: bool = True
