"""Cisco ACI reads for Ask the Net, run as the calling user.

``DbAciReader`` checks ``sources.aci:read`` on every call and returns the usable APIC sources as
ready-built services (doc/plans/ACI_TOOL_CHAIN.md). Credentials resolve here and never reach a
tool. A source whose credentials do not load is skipped and logged with its error type only.
No source at all is ``AciNotConfiguredError``; sources that all fail to load are
``AciSourcesUnusableError``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import service_factory
from core.database import SessionLocal
from services.aci.details_service import AciDetailsService
from services.aci.device_service import AciDeviceService
from services.aci.endpoint_service import AciEndpointService
from services.aci.policy_service import AciPolicyService
from services.aci.subnet_service import AciSubnetService
from services.auth.rbac_service import RBACService

logger = logging.getLogger(__name__)


class AciAccessError(Exception):
    """The user may not read ACI sources."""


class AciNotConfiguredError(Exception):
    """No ACI source is configured."""


class AciSourcesUnusableError(Exception):
    """Sources exist but none loads (credentials or settings fail)."""


@dataclass(frozen=True)
class AciSource:
    source_id: str
    devices: AciDeviceService
    details: AciDetailsService
    endpoints: AciEndpointService
    subnets: AciSubnetService
    policy: AciPolicyService
    # Identifies the fabric and its credentials; keys the policy snapshot cache.
    cache_key: str = ""


def _cache_key(source_id: str, credentials: Any) -> str:
    """Source id plus a digest of the URL and credentials, so a changed password is a new key."""
    digest = hashlib.sha256(
        f"{credentials.base_url}\0{credentials.login_name}\0{credentials.password}".encode()
    ).hexdigest()[:16]
    return f"{source_id}:{digest}"


class DbAciReader:
    """Builds the sources of one user; ``sources()`` raises the errors above."""

    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    def _build(self) -> tuple[AciSource, ...]:
        with SessionLocal() as db:
            if not RBACService(db).has_permission(self._user_id, "sources.aci", "read"):
                raise AciAccessError
            config = service_factory.build_aci_source_config_service(db)
            rows = config.list_sources()
            usable: list[AciSource] = []
            for row in rows:
                source_id = str(row["source_id"])
                try:
                    credentials = config.resolve_credentials(source_id)
                except Exception as exc:  # an unusable source must not hide a usable one
                    logger.warning(
                        "AI assistant: ACI source %r unavailable (%s)",
                        source_id,
                        type(exc).__name__,
                    )
                    continue
                usable.append(
                    AciSource(
                        source_id=source_id,
                        devices=service_factory.build_aci_device_service(credentials),
                        details=service_factory.build_aci_details_service(credentials),
                        endpoints=service_factory.build_aci_endpoint_service(credentials),
                        subnets=service_factory.build_aci_subnet_service(credentials),
                        policy=service_factory.build_aci_policy_service(credentials),
                        cache_key=_cache_key(source_id, credentials),
                    )
                )
        if not usable:
            if rows:
                logger.warning("AI assistant: none of the %d ACI source(s) is usable", len(rows))
                raise AciSourcesUnusableError
            logger.info("AI assistant: no ACI source is configured")
            raise AciNotConfiguredError
        return tuple(usable)

    async def sources(self) -> tuple[AciSource, ...]:
        return await asyncio.to_thread(self._build)
