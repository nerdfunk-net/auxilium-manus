"""Paged reads of the SD-Access (``/sda``) list endpoints.

Verified live (Catalyst Center 3.723, DevNet sandbox): ``limit`` is 1..500 and ``offset`` starts
at 1; the body is ``{"response": [...]}``.
"""

from __future__ import annotations

from typing import Any

from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.credentials import CatalystCenterCredentials

SDA_PAGE_SIZE = 500
_MAX_PAGES = 50


async def read_sda_pages(
    client: CatalystCenterService,
    credentials: CatalystCenterCredentials,
    path: str,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """All records of a paged ``{"response": [...]}`` list (1-based offset)."""
    records: list[dict[str, Any]] = []
    for page in range(_MAX_PAGES):
        payload = await client.request(
            credentials,
            "GET",
            path,
            params={**params, "offset": 1 + page * SDA_PAGE_SIZE, "limit": SDA_PAGE_SIZE},
        )
        body = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(body, list):
            raise CatalystCenterValidationError(
                "Catalyst Center returned an unexpected SD-Access response"
            )
        records.extend(item for item in body if isinstance(item, dict))
        if len(body) < SDA_PAGE_SIZE:
            return records
    raise CatalystCenterValidationError("Catalyst Center SD-Access list exceeded page bound")
