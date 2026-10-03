"""Catalyst Center release parsing and capability gates.

Doc: doc/CATALYST_CENTER_API_DIFF.md. For the endpoints this integration uses, the
2.3.3.x / 2.3.7.x / 3.x lines share one endpoint set; the only difference found is that
``GET /network-device/count`` accepts filters from 2.3.7 on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from services.catalyst_center.common.exceptions import CatalystCenterValidationError

_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?")
_FILTERED_COUNT_SINCE = (2, 3, 7, 0)
# Real product releases look like 2.3.7.9 / 3.1.6. Some controllers report an internal
# platform build (e.g. "3.722.75335") in the same field; reject those instead of guessing.
_MAX_COMPONENT = 99


@dataclass(frozen=True, order=False)
class CatalystCenterRelease:
    major: int
    minor: int
    patch: int
    build: int = 0
    raw: str = ""

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.major, self.minor, self.patch, self.build)

    def __lt__(self, other: CatalystCenterRelease) -> bool:
        return self.as_tuple() < other.as_tuple()

    def __gt__(self, other: CatalystCenterRelease) -> bool:
        return self.as_tuple() > other.as_tuple()

    @property
    def supports_filtered_device_count(self) -> bool:
        """``/network-device/count`` honours hostname/IP/MAC/location filters."""
        return self.as_tuple() >= _FILTERED_COUNT_SINCE


def parse_release(raw: Any) -> CatalystCenterRelease:
    """Parse ``2.3.7.9``, ``2.3.7.9-70050`` or ``3.1.6`` into a release."""
    text = raw.strip() if isinstance(raw, str) else ""
    match = _VERSION_RE.match(text)
    if match is None:
        raise CatalystCenterValidationError("Unrecognised Catalyst Center release string")
    major, minor, patch, build = (int(part or 0) for part in match.groups())
    if max(major, minor, patch, build) > _MAX_COMPONENT:
        raise CatalystCenterValidationError("Not a Catalyst Center product release string")
    return CatalystCenterRelease(major, minor, patch, build, raw=text)


def release_from_payload(payload: Any) -> CatalystCenterRelease:
    """Extract the release from a ``GET /dnac-release`` response body.

    Raises when the controller reports no version, or reports something that is not a
    product release (the DevNet sandbox returns the platform build ``3.722.75335``).
    """
    label = installed_version_label(payload)
    if label is None:
        raise CatalystCenterValidationError("Catalyst Center release response has no version")
    return parse_release(label)


def installed_version_label(payload: Any) -> str | None:
    """The version string a controller reports in ``GET /dnac-release``, verbatim.

    Display only: it may be a product release (2.3.7.9) or an internal platform build
    (observed live: ``3.722.75335``); use :func:`release_from_payload` for gating.
    """
    body = payload.get("response") if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        return None
    for key in ("installedVersion", "version"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
