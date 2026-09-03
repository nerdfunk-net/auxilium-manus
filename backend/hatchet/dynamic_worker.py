"""Second Hatchet worker process — registers one dedicated Hatchet workflow
per row in workflow_background_tier, each running the same prepare/
execute_steps shape as WorkflowExecution but under its own name (so Hatchet-
native per-workflow concurrency limits apply) and on a separate worker pool
from the live/interactive WorkflowExecution worker (hatchet/worker.py) — so a
slow/limited background run never starves live one-shot runs, and vice versa.

Run as a separate process alongside worker.py:

    cd backend
    source ../.venv/bin/activate
    python -m hatchet.dynamic_worker

No hot-reload (same limitation as worker.py); use
scripts/run_dynamic_worker_dev.py in development instead.

The set of registered workflows is fixed at process start, per Hatchet's own
worker-registration model — a newly published, edited, or unpublished
background-tier workflow only takes effect once this process restarts. A
background task polls Postgres every DYNAMIC_WORKER_POLL_INTERVAL_SECONDS and
self-terminates on any change (see _self_restart_on_change below); supervisord
(`stopsignal=TERM`, `autorestart=true`, `stopwaitsecs=600`) brings the process
back up with a freshly-queried set.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from collections.abc import AsyncGenerator, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from core.cert_installer import install_certificates  # noqa: E402
from core.database import SessionLocal  # noqa: E402
from core.logging_config import (  # noqa: E402
    BACKGROUND_WORKER_PROCESS_NAME,
    configure_logging,
)
from hatchet import worker_services  # noqa: E402
from hatchet.client import hatchet  # noqa: E402
from hatchet.dynamic_worker_config import (  # noqa: E402
    DYNAMIC_WORKER_NAME,
    DYNAMIC_WORKER_POLL_INTERVAL_SECONDS,
    DYNAMIC_WORKER_SLOTS,
)
from hatchet.workflows.device_group_execution import (  # noqa: E402
    child_workflow as device_group_workflow,
)
from hatchet.workflows.workflow_run import build_workflow_execution  # noqa: E402
from repositories.background_tier_repository import BackgroundTierRepository  # noqa: E402

if TYPE_CHECKING:
    from hatchet_sdk.runnables.workflow import Workflow as HatchetWorkflow

    from core.models.background_tier import WorkflowBackgroundTier

configure_logging(BACKGROUND_WORKER_PROCESS_NAME)
logger = logging.getLogger(__name__)


def _load_published_workflows() -> tuple[
    list[WorkflowBackgroundTier], tuple[int, datetime | None]
]:
    with SessionLocal() as db:
        repo = BackgroundTierRepository(db)
        rows = repo.list_all()
        fingerprint = repo.fingerprint()
    return rows, fingerprint


def _build_dynamic_workflows(
    rows: list[WorkflowBackgroundTier],
) -> list[HatchetWorkflow]:
    return [
        build_workflow_execution(name=row.hatchet_workflow_name, concurrency=row.concurrency_limit)
        for row in rows
    ]


async def _self_restart_on_change(
    initial_fingerprint: tuple[int, datetime | None], poll_interval_seconds: int
) -> None:
    """Exit (SIGTERM) once the published set changes, so supervisord's
    autorestart brings this process back up with a fresh registration —
    reusing the same graceful-shutdown path a normal supervised stop already
    exercises, rather than inventing a new one."""
    while True:
        await asyncio.sleep(poll_interval_seconds)
        with SessionLocal() as db:
            fingerprint = BackgroundTierRepository(db).fingerprint()
        if fingerprint != initial_fingerprint:
            logger.info(
                "Background-tier registration changed (was %s, now %s) — restarting to pick up",
                initial_fingerprint,
                fingerprint,
            )
            os.kill(os.getpid(), signal.SIGTERM)
            return


def _make_lifespan(
    initial_fingerprint: tuple[int, datetime | None],
) -> Callable[[], AsyncGenerator[None]]:
    async def lifespan() -> AsyncGenerator[None]:
        async with worker_services.start_all(BACKGROUND_WORKER_PROCESS_NAME):
            watcher = asyncio.create_task(
                _self_restart_on_change(
                    initial_fingerprint, DYNAMIC_WORKER_POLL_INTERVAL_SECONDS
                )
            )
            try:
                yield
            finally:
                watcher.cancel()

    return lifespan


def main() -> None:
    # Install operator-supplied CA certificates before any outbound call.
    install_certificates()
    rows, fingerprint = _load_published_workflows()
    dynamic_workflows = _build_dynamic_workflows(rows)
    logger.info(
        "Dynamic worker starting with %d published background-tier workflow(s)",
        len(dynamic_workflows),
    )

    worker = hatchet.worker(
        DYNAMIC_WORKER_NAME,
        slots=DYNAMIC_WORKER_SLOTS,
        workflows=[*dynamic_workflows, device_group_workflow],
        lifespan=_make_lifespan(fingerprint),
    )
    logger.info("Starting Hatchet dynamic worker — background-tier workflows only")
    worker.start()


if __name__ == "__main__":
    main()
