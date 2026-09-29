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

# Started on demand by the "Rebuild cache" button (POST /cache/rebuild); never
# scheduled. Same routine as the cron, but forced — see refresh_nautobot_device_caches.
rebuild_workflow = hatchet.workflow(name="RebuildNautobotDeviceCache")


async def refresh_nautobot_device_caches(*, force: bool) -> dict[str, int]:
    """Reload the bulk device cache of every configured Nautobot source.

    ``force=False`` (the 5-minute cron) only drops derived entries when the
    device data changed. ``force=True`` (Rebuild) always drops them — location
    filters and per-device details/attributes — before repopulating from
    Nautobot. One failing source never stops the others.
    """
    import service_factory
    from core.database import SessionLocal
    from repositories.settings_repository import SettingsRepository
    from services.settings.settings_service import SettingsService
    from services.settings.source_keys import parse_source_key

    with SessionLocal() as db:
        settings = SettingsRepository(db).list_all(key_prefix=NAUTOBOT_KEY_PREFIX)
        source_ids = [
            parsed[1]
            for setting in settings
            if (parsed := parse_source_key(setting.key)) is not None
        ]

    refreshed = 0
    failed = 0
    devices = 0

    for source_id in source_ids:
        key = f"{NAUTOBOT_KEY_PREFIX}{source_id}"
        try:
            with SessionLocal() as db:
                # get_source_config decrypts the linked vault credential into "token".
                config = SettingsService(db).get_source_config("nautobot", source_id)
            url = str(config.get("url") or "")
            token = str(config.get("token") or "")
            if not url or not token:
                logger.warning("Skipping Nautobot source '%s': missing url/token", key)
                continue

            credentials = service_factory.credentials_from_connection(url, token)
            with SessionLocal() as db:
                source_service = service_factory.build_nautobot_source_service(credentials, db)
                count = await source_service.refresh_bulk_device_cache(force=force)
            logger.info(
                "Refreshed bulk device cache for '%s': %s devices (force=%s)", key, count, force
            )
            refreshed += 1
            devices += count
        except Exception:
            failed += 1
            logger.exception("Failed to refresh bulk device cache for '%s'", key)

    logger.info(
        "Nautobot device cache refresh complete (force=%s): %s/%s source(s) refreshed, %s failed",
        force,
        refreshed,
        len(source_ids),
        failed,
    )
    return {
        "sources": len(source_ids),
        "refreshed": refreshed,
        "failed": failed,
        "devices": devices,
    }


@workflow.task(name="refresh_all_sources")
async def refresh_all_sources(input: EmptyModel, ctx: Context) -> dict[str, int]:
    return await refresh_nautobot_device_caches(force=False)


@rebuild_workflow.task(name="rebuild_all_sources")
async def rebuild_all_sources(input: EmptyModel, ctx: Context) -> dict[str, int]:
    return await refresh_nautobot_device_caches(force=True)
