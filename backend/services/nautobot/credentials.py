from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class NautobotCredentials:
    url: str
    token: str
    timeout: float = 30.0
    verify_ssl: bool = True

    @property
    def cache_scope(self) -> str:
        """Stable scope for Redis keys (per Nautobot instance + token)."""
        digest = hashlib.sha256(f"{self.url}:{self.token}".encode()).hexdigest()
        return digest[:16]
