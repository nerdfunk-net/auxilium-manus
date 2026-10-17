"""Shared service-startup/shutdown block: the one place the app-scoped services are started and
stopped, for the API (main.py) and for any Hatchet worker process (worker.py, dynamic_worker.py).
A new app-scoped service is registered here and nowhere else.

Both workers run the same task code
(prepare/execute_steps, DeviceGroupExecution) and therefore need the same
app-service singletons wired into service_factory before accepting work.
service_factory itself holds no cross-process state, so each worker process
initializing it independently is safe.

Each worker passes its own ``process_name`` (see core.logging_config) so the
persisted logging overrides are re-applied to the correct per-process log sink
— the live worker keeps ``worker.log``; the background-tier worker gets its
own ``worker-background.log`` and never shares a RotatingFileHandler file.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import service_factory
from core.database import SessionLocal
from core.logging_config import WORKER_PROCESS_NAME
from services.batfish.client import BatfishService
from services.catalyst_center.client import CatalystCenterService
from services.ise.client import ISEService
from services.logging.logging_settings_service import LoggingSettingsService
from services.mattermost.client import MattermostService
from services.nautobot.client import NautobotService
from services.pyats.client import PyATSShimService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def start_all(
    process_name: str = WORKER_PROCESS_NAME,
    *,
    with_management: bool = False,
    apply_logging: bool = True,
) -> AsyncIterator[None]:
    """Start the app services, yield, then stop them (also when the body raises).

    ``with_management`` is True only for the API process, which alone may write to OpenBao (V5).
    ``apply_logging`` is False when the caller already applied the persisted logging overrides.
    """
    if apply_logging:
        with SessionLocal() as db:
            LoggingSettingsService(db).apply_to_current_process(process_name)

    nautobot_service = NautobotService()
    await nautobot_service.startup()
    service_factory.set_nautobot_app_service(nautobot_service)

    ise_service = ISEService()
    await ise_service.startup()
    service_factory.set_ise_app_service(ise_service)

    catalyst_center_service = CatalystCenterService()
    await catalyst_center_service.startup()
    service_factory.set_catalyst_center_app_service(catalyst_center_service)

    pyats_service = PyATSShimService()
    await pyats_service.startup()
    service_factory.set_pyats_app_service(pyats_service)

    batfish_service = BatfishService()
    await batfish_service.startup()
    service_factory.set_batfish_app_service(batfish_service)

    mattermost_service = MattermostService()
    await mattermost_service.startup()
    service_factory.set_mattermost_app_service(mattermost_service)

    # OpenBao (Vault) — no-op unless VAULT_ENABLED. Each process holds its own runtime token +
    # renewal loop; workers only read, so no management (write-capable) login (V5).
    # See doc/VAULT_INTEGRATION.md.
    from core.vault import start_vault_services, stop_vault_services

    await start_vault_services(with_management=with_management)

    service_factory.build_cache_service()
    logger.info("Services initialized for process=%s", process_name)
    try:
        yield
    finally:
        await nautobot_service.shutdown()
        await ise_service.shutdown()
        await catalyst_center_service.shutdown()
        await pyats_service.shutdown()
        await batfish_service.shutdown()
        await mattermost_service.shutdown()
        await stop_vault_services()
        await service_factory.stop_secret_manager_services()
        logger.info("Services shut down for process=%s", process_name)
