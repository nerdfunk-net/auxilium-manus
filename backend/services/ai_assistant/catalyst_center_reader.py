"""Cisco Catalyst Center reads for Ask the Net, run as the calling user.

``DbCatalystCenterReader`` checks ``sources.catalyst_center:read`` on every call and returns the
usable Catalyst Center sources as ready-built device and details services (doc/AI_TOOL_CHAIN.md
§42). Credentials resolve here and never reach a tool: a tool only sees the services.

A source whose credentials do not load is skipped and logged with its error type only (the
message and traceback can carry credential text). No source at all is
``CatalystNotConfiguredError``; sources that all fail to load are
``CatalystSourcesUnusableError``: the user needs different advice for each.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import service_factory
from core.database import SessionLocal
from services.auth.rbac_service import RBACService
from services.catalyst_center.details_service import CatalystCenterDetailsService
from services.catalyst_center.device_service import CatalystCenterDeviceService

logger = logging.getLogger(__name__)


class CatalystAccessError(Exception):
    """The user may not read Catalyst Center sources."""


class CatalystNotConfiguredError(Exception):
    """No Catalyst Center source is configured."""


class CatalystSourcesUnusableError(Exception):
    """Sources exist but none loads (credentials or settings fail): not the same as missing."""


@dataclass(frozen=True)
class CatalystSource:
    source_id: str
    devices: CatalystCenterDeviceService
    details: CatalystCenterDetailsService


class DbCatalystCenterReader:
    """Builds the sources of one user; ``sources()`` raises the two errors above."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    def _build(self) -> tuple[CatalystSource, ...]:
        with SessionLocal() as db:
            if not RBACService(db).has_permission(self._user_id, "sources.catalyst_center", "read"):
                raise CatalystAccessError
            config = service_factory.build_catalyst_center_source_config_service(db)
            rows = config.list_sources()
            usable: list[CatalystSource] = []
            for row in rows:
                source_id = str(row["source_id"])
                try:
                    credentials = config.resolve_credentials(source_id)
                except Exception as exc:  # an unusable source must not hide a usable one
                    logger.warning(
                        "AI assistant: Catalyst Center source %r unavailable (%s)",
                        source_id,
                        type(exc).__name__,
                    )
                    continue
                usable.append(
                    CatalystSource(
                        source_id=source_id,
                        devices=service_factory.build_catalyst_center_device_service(credentials),
                        details=service_factory.build_catalyst_center_details_service(credentials),
                    )
                )
        if not usable:
            if rows:
                logger.warning(
                    "AI assistant: none of the %d Catalyst Center source(s) is usable", len(rows)
                )
                raise CatalystSourcesUnusableError
            logger.info("AI assistant: no Catalyst Center source is configured")
            raise CatalystNotConfiguredError
        return tuple(usable)

    async def sources(self) -> tuple[CatalystSource, ...]:
        return await asyncio.to_thread(self._build)
