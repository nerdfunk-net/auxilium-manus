from __future__ import annotations

import logging

from hatchet_sdk import Hatchet

from core.config import settings

logger = logging.getLogger(__name__)

_hatchet: Hatchet | None = None


def get_hatchet() -> Hatchet:
    global _hatchet
    if _hatchet is None:
        _hatchet = Hatchet(
            token=settings.hatchet_token or None,
            host_port=settings.hatchet_host_port,
            debug=settings.hatchet_debug,
        )
    return _hatchet


# Module-level alias used by workflow and worker modules
hatchet = get_hatchet()
