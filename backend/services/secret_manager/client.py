"""``SecretManagerClient`` protocol every backend adapter implements.

Field-granular rather than whole-dict, because the three consumers
(``secret-get``/``secret-set``/``secret-generate`` executors) always operate
on one field at one path at a time. A path may hold several fields (e.g.
``network/router1/tacacs`` -> ``{"key": ..., "rotated_at": ...}``); each
backend maps that onto its own native storage shape (OpenBao: one KV v2 dict
at the path).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SecretVersionInfo:
    version: int
    created_at: str  # ISO 8601


class SecretManagerClient(Protocol):
    async def ensure_started(self) -> None:
        """Perform any async startup (e.g. an OpenBao token-renewal loop).
        Called once by the registry before first use; a no-op for backends
        that don't need one."""
        ...

    def get_field(self, path: str, field: str, *, version: int | None = None) -> str | None: ...

    def set_field(self, path: str, field: str, value: str) -> int | None:
        """Write *value*; return the new version number when the backend reports one."""
        ...

    def get_field_history(self, path: str, field: str) -> list[SecretVersionInfo]:
        """Version history, newest first."""
        ...

    async def shutdown(self) -> None:
        """Release any held resources (background renew tasks, connections)."""
        ...
