"""Catalyst Center version label for display.

Doc: doc/CATALYST_CENTER_API_DIFF.md. For the endpoints this integration uses, the
2.3.3.x / 2.3.7.x / 3.x lines share one endpoint set, so nothing is gated on the release.
Release gating (``CatalystCenterRelease`` / ``GET /network-device/count`` with filters from 2.3.7)
was removed because nothing consumed it; ``git log -- services/catalyst_center/common/version.py``
has it if a future endpoint really diverges.
"""

from __future__ import annotations

from typing import Any


def installed_version_label(payload: Any) -> str | None:
    """The version string a controller reports in ``GET /dnac-release``, verbatim.

    Display only: it may be a product release (2.3.7.9) or an internal platform build
    (observed live: ``3.722.75335``).
    """
    body = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        return None
    for key in ("installedVersion", "version"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
