"""Per-request Cisco ISE ERS credentials."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ISECredentials:
    base_url: str
    username: str
    password: str
    timeout: float = 30.0
    verify_ssl: bool = True
