from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class BackgroundTierUpsert(BaseModel):
    concurrency_limit: int | None = None  # None = unlimited


class BackgroundTierResponse(BaseModel):
    id: int
    uuid: str
    workflow_id: int
    hatchet_workflow_name: str
    concurrency_limit: int | None
    published_by_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
