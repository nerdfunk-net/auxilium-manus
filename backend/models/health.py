from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ReadyCheck(BaseModel):
    ok: bool
    error: str | None = None


class ReadyResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    database: ReadyCheck
    redis: ReadyCheck
    # Present only when VAULT_ENABLED. Informational: a vault outage degrades
    # vault-backed credentials, it does not make the API unready (V12).
    vault: ReadyCheck | None = None
