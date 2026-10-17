from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HatchetConfigResponse(BaseModel):
    """Read-only snapshot of the live Hatchet client configuration.

    Most values are resolved from HATCHET_CLIENT_* environment variables (see
    hatchet/client.py); worker_name/worker_slots come from HATCHET_WORKER_*
    environment variables (see hatchet/worker_config.py), and the
    dynamic_worker_* fields come from HATCHET_DYNAMIC_WORKER_* (see
    hatchet/dynamic_worker_config.py) — the second worker process that hosts
    workflows published to the background tier (doc/ARCHITECTURAL_OVERVIEW.md
    -> "Background-tier workflows"). sdk_version is the installed hatchet-sdk
    package version (client-side only — the Hatchet engine/server does not
    expose its version over the REST API). There is no app-side override for
    any of these — this endpoint is purely informational, and reports what
    THIS process (the API) resolved for both workers' config, not a live
    health check of either worker process (see check_connection for that,
    which only probes the shared Hatchet engine, not a specific worker).

    dashboard_url is the one exception: it is the browser-reachable URL used by
    the "Open Dashboard" link in the UI. server_url is what the backend process
    itself uses to reach the Hatchet REST API, which in a reverse-proxied/Docker
    setup (e.g. Traefik) is often a network-internal address the browser cannot
    resolve. dashboard_url defaults to server_url but can be overridden with
    HATCHET_DASHBOARD_URL when the two must differ.
    """

    server_url: str
    dashboard_url: str
    host_port: str
    tenant_id: str
    namespace: str
    tls_strategy: str
    debug: bool
    token_configured: bool
    worker_name: str
    worker_slots: int
    dynamic_worker_name: str
    dynamic_worker_slots: int
    dynamic_worker_poll_interval_seconds: int
    sdk_version: str


class HatchetStatusResponse(HatchetConfigResponse):
    reachable: bool
    message: str
    checked_at: datetime
