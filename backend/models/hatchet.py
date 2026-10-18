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


class HatchetTaskInfo(BaseModel):
    """One engine-side task of a run. No input/output: those can hold device data."""

    name: str
    status: str
    attempt: int | None = None
    retry_count: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None


class HatchetTaskEventInfo(BaseModel):
    task_name: str | None = None
    event_type: str
    timestamp: datetime
    message: str
    error_message: str | None = None
    attempt: int | None = None


class HatchetChildRun(BaseModel):
    """A fan-out device-group run found through the ``parent_run_id`` metadata."""

    hatchet_run_id: str
    name: str
    status: str
    child_index: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class HatchetChildSummary(BaseModel):
    """Counts of a run's fan-out groups by engine status.

    ``exact`` is False when the engine's metrics call was unavailable and the counts come from
    the listed rows only. ``truncated`` means some groups that need attention are not listed.
    """

    total: int
    completed: int
    failed: int
    cancelled: int
    running: int
    queued: int
    exact: bool
    listed: int
    truncated: bool


class HatchetRunDiagnostics(BaseModel):
    """What the Hatchet engine reports for one of our runs (operator view)."""

    engine_reachable: bool
    message: str
    hatchet_run_id: str | None = None
    engine_status: str | None = None
    # Set when our run status and the engine status disagree (lost worker, dead engine).
    mismatch: str | None = None
    dashboard_url: str | None = None
    tasks: list[HatchetTaskInfo] = []
    events: list[HatchetTaskEventInfo] = []
    # Failed/cancelled groups first, then running, then queued; completed groups are only counted.
    child_runs: list[HatchetChildRun] = []
    child_summary: HatchetChildSummary | None = None
    events_truncated: bool = False


class HatchetWorkerInfo(BaseModel):
    # Engine id: several rows can share a name (a restarted worker leaves an inactive one behind).
    id: str
    name: str
    status: str | None = None
    type: str | None = None
    last_heartbeat_at: datetime | None = None
    slots_used: int | None = None
    slots_total: int | None = None
    registered_workflows: list[str] = []


class HatchetWorkersResponse(BaseModel):
    engine_reachable: bool
    message: str
    workers: list[HatchetWorkerInfo] = []
    # Configured worker names (live + background) that the engine does not list as active.
    missing_workers: list[str] = []
