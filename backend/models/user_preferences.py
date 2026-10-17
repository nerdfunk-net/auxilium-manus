from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class DashboardLayoutUpdate(BaseModel):
    layout: dict[str, Any]


class DashboardLayoutResponse(BaseModel):
    layout: dict[str, Any] | None
