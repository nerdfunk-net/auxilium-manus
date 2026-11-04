"""Detect the Nautobot server version (``GET /api/status/``).

Cable GraphQL differs between Nautobot < 3.2 and >= 3.2, so the cable query is
chosen per server. A failed or unparsable lookup yields ``None`` (callers treat that
as the older layout). Nothing is cached here: a server swapped behind the same URL
must be seen at once, and the lookup is one cheap request per query build.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.nautobot.client import NautobotService
    from services.nautobot.credentials import NautobotCredentials

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)")


def parse_nautobot_version(raw: object) -> tuple[int, int] | None:
    """``"3.1.1"`` -> ``(3, 1)``; anything unparsable -> ``None``."""
    match = _VERSION_RE.match(raw) if isinstance(raw, str) else None
    return (int(match.group(1)), int(match.group(2))) if match else None


async def detect_nautobot_version(
    service: NautobotService, credentials: NautobotCredentials
) -> tuple[int, int] | None:
    """Return the server's ``(major, minor)``, or ``None`` if it cannot be read."""
    try:
        payload = await service.test_connection(credentials)
    except Exception:
        logger.warning("Nautobot version unreadable; assuming pre-3.2 layout", exc_info=True)
        return None
    raw = (payload or {}).get("nautobot-version") or (payload or {}).get("nautobot_version")
    version = parse_nautobot_version(raw)
    if version is None:
        logger.warning("Unrecognised Nautobot version %r; assuming the pre-3.2 layout", raw)
    return version
