"""Hatchet worker entry point.

Run as a separate process alongside the FastAPI server:

    cd backend
    source ../.venv/bin/activate
    python -m hatchet.worker

This process has no hot-reload: unlike the FastAPI app (uvicorn `reload=True`
in development), code changes require killing and restarting this process.
For development, use `python scripts/run_worker_dev.py` instead — it restarts
this module automatically on .py changes under backend/.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from core.cert_installer import install_certificates  # noqa: E402
from core.logging_config import WORKER_PROCESS_NAME, configure_logging  # noqa: E402
from hatchet import worker_services  # noqa: E402
from hatchet.client import hatchet  # noqa: E402
from hatchet.worker_config import WORKER_NAME, WORKER_SLOTS  # noqa: E402
from hatchet.workflows.cache_devices import workflow as cache_devices_workflow  # noqa: E402
from hatchet.workflows.device_group_execution import (  # noqa: E402
    child_workflow as device_group_workflow,
)
from hatchet.workflows.purge_retention import workflow as purge_retention_workflow  # noqa: E402
from hatchet.workflows.scheduled_trigger import workflow as scheduled_trigger_workflow  # noqa: E402
from hatchet.workflows.workflow_run import workflow as workflow_execution  # noqa: E402

configure_logging(WORKER_PROCESS_NAME)
logger = logging.getLogger(__name__)


async def lifespan() -> AsyncGenerator[None, None]:
    async with worker_services.start_all(WORKER_PROCESS_NAME):
        yield


def main() -> None:
    # Install operator-supplied CA certificates before any outbound call.
    install_certificates()
    worker = hatchet.worker(
        WORKER_NAME,
        slots=WORKER_SLOTS,
        workflows=[
            workflow_execution,
            device_group_workflow,
            cache_devices_workflow,
            scheduled_trigger_workflow,
            purge_retention_workflow,
        ],
        lifespan=lifespan,
    )
    logger.info("Starting Hatchet worker — listening for workflow:run events")
    worker.start()


if __name__ == "__main__":
    main()
