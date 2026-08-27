"""Shared service-startup/shutdown block for any Hatchet worker process
(worker.py, dynamic_worker.py). Both workers run the same task code
(prepare/execute_steps, DeviceGroupExecution) and therefore need the same
app-service singletons wired into service_factory before accepting work.
service_factory itself holds no cross-process state, so each worker process
initializing it independently is safe.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import service_factory
from core.database import SessionLocal
from services.ise.client import ISEService
from services.logging.logging_settings_service import LoggingSettingsService
from services.mattermost.client import MattermostService
from services.nautobot.client import NautobotService
from services.pyats.client import PyATSShimService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def start_all() -> AsyncIterator[None]:
    with SessionLocal() as db:
        LoggingSettingsService(db).apply_to_current_process("worker")

    nautobot_service = NautobotService()
    await nautobot_service.startup()
    service_factory.set_nautobot_app_service(nautobot_service)

    ise_service = ISEService()
    await ise_service.startup()
    service_factory.set_ise_app_service(ise_service)

    pyats_service = PyATSShimService()
    await pyats_service.startup()
    service_factory.set_pyats_app_service(pyats_service)

    mattermost_service = MattermostService()
    await mattermost_service.startup()
    service_factory.set_mattermost_app_service(mattermost_service)

    service_factory.build_cache_service()
    logger.info("Worker services initialized")
    try:
        yield
    finally:
        await nautobot_service.shutdown()
        await ise_service.shutdown()
        await pyats_service.shutdown()
        await mattermost_service.shutdown()
        logger.info("Worker services shut down")
