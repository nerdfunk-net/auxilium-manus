"""Periodic Hatchet workflow that keeps the Nautobot bulk device cache warm.

The inventory preview path (NautobotSourceQueryService._get_all_devices_cached,
see services/sources/nautobot/query_service.py) only *reads* the Redis bulk key
`nautobot:devices:all:<scope>` — something else has to write it. In the original
cockpit app this was a Celery Beat task (cache_all_devices_task) running every 5
minutes; auxilium-manus dropped Celery for Hatchet and never got an equivalent
scheduled job, so the bulk key was never populated and every preview fell back to
a live Nautobot API call. This cron-triggered workflow is that replacement writer.
"""

from __future__ import annotations

import logging

from hatchet_sdk import Context, EmptyModel

from hatchet.client import hatchet
from services.settings.source_keys import NAUTOBOT_KEY_PREFIX

logger = logging.getLogger(__name__)

workflow = hatchet.workflow(
    name="RefreshNautobotDeviceCache",
    on_crons=["*/5 * * * *"],
)


@workflow.task(name="refresh_all_sources")
async def refresh_all_sources(input: EmptyModel, ctx: Context) -> dict:
    import service_factory
    from core.database import SessionLocal
    from repositories.settings_repository import SettingsRepository

    with SessionLocal() as db:
        settings = SettingsRepository(db).list_all(key_prefix=NAUTOBOT_KEY_PREFIX)
        sources = [(setting.key, dict(setting.value or {})) for setting in settings]

    refreshed = 0
    failed = 0

    for key, value in sources:
        url = value.get("url")
        token = value.get("token")
        if not url or not token:
            logger.warning("Skipping Nautobot source '%s': missing url/token", key)
            continue

        try:
            credentials = service_factory.credentials_from_connection(url, token)
            with SessionLocal() as db:
                source_service = service_factory.build_nautobot_source_service(credentials, db)
                count = await source_service.refresh_bulk_device_cache()
            logger.info("Refreshed bulk device cache for '%s': %s devices", key, count)
            refreshed += 1
        except Exception:
            failed += 1
            logger.exception("Failed to refresh bulk device cache for '%s'", key)

    logger.info(
        "RefreshNautobotDeviceCache complete: %s/%s source(s) refreshed, %s failed",
        refreshed,
        len(sources),
        failed,
    )
    return {"refreshed": refreshed, "failed": failed, "total": len(sources)}
