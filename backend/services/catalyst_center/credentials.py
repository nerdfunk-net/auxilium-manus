"""Per-request Cisco Catalyst Center connection credentials."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CatalystCenterCredentials:
    base_url: str
    username: str
    password: str
    timeout: float = 30.0
    verify_ssl: bool = True
