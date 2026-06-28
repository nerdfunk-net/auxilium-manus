"""Hatchet worker entry point.

Run as a separate process alongside the FastAPI server:

    cd backend
    source ../.venv/bin/activate
    python -m hatchet.worker
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

import service_factory  # noqa: E402
from hatchet.client import hatchet  # noqa: E402
from hatchet.workflows.device_group_execution import (  # noqa: E402
    child_workflow as device_group_workflow,
)
from hatchet.workflows.workflow_run import workflow as workflow_execution  # noqa: E402
from services.nautobot.client import NautobotService  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def lifespan() -> AsyncGenerator[None, None]:
    nautobot_service = NautobotService()
    await nautobot_service.startup()
    service_factory.set_nautobot_app_service(nautobot_service)
    service_factory.build_cache_service()
    logger.info("Worker services initialized")
    try:
        yield
    finally:
        await nautobot_service.shutdown()
        logger.info("Worker services shut down")


def main() -> None:
    worker = hatchet.worker(
        "auxilium-manus-worker",
        slots=10,
        workflows=[workflow_execution, device_group_workflow],
        lifespan=lifespan,
    )
    logger.info("Starting Hatchet worker — listening for workflow:run events")
    worker.start()


if __name__ == "__main__":
    main()
