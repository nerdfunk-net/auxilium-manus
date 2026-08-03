from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HatchetConfigResponse(BaseModel):
    """Read-only snapshot of the live Hatchet client configuration.

    Most values are resolved from HATCHET_CLIENT_* environment variables (see
    hatchet/client.py); worker_name/worker_slots come from HATCHET_WORKER_*
    environment variables (see hatchet/worker_config.py). sdk_version is the
    installed hatchet-sdk package version (client-side only — the Hatchet
    engine/server does not expose its version over the REST API). There is no
    app-side override for any of these — this endpoint is purely informational.
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
    sdk_version: str


class HatchetStatusResponse(HatchetConfigResponse):
    reachable: bool
    message: str
    checked_at: datetime
