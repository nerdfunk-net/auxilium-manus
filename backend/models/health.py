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
