"""Validation of controller-issued ids before they are placed in a request path."""

from __future__ import annotations

import re

from services.catalyst_center.common.exceptions import CatalystCenterValidationError

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def safe_device_id(device_id: str) -> str:
    """Reject ids (device, site, task, file) that could alter the request path."""
    if not isinstance(device_id, str) or not _ID_RE.fullmatch(device_id):
        raise CatalystCenterValidationError("Invalid Catalyst Center device id")
    return device_id
