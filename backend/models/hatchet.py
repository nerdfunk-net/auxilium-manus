from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HatchetConfigResponse(BaseModel):
    """Read-only snapshot of the live Hatchet client configuration.

    All values are resolved from HATCHET_CLIENT_* environment variables (see
    hatchet/client.py) — there is no app-side override, so this endpoint is
    purely informational.
    """

    server_url: str
    host_port: str
    tenant_id: str
    namespace: str
    tls_strategy: str
    debug: bool
    token_configured: bool
    worker_name: str
    worker_slots: int


class HatchetStatusResponse(HatchetConfigResponse):
    reachable: bool
    message: str
    checked_at: datetime
