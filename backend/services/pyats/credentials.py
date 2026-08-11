"""Per-request pyATS shim connection settings and bearer token."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PyATSCredentials:
    base_url: str
    token: str
    timeout: float = 30.0
    verify_ssl: bool = False
