"""REST path helpers: value quoting and bounded pagination."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

MAX_REST_PAGES = 50


def rest_query(**params: Any) -> str:
    """Build a query string with every value percent-encoded (``&``, ``#``, ``+`` safe)."""
    return "&".join(
        f"{quote(str(key), safe='')}={quote(str(value), safe='')}" for key, value in params.items()
    )


def _next_endpoint(next_url: str, endpoint: str) -> str:
    """Turn an absolute ``next`` link into an endpoint relative to the API root."""
    parts = urlsplit(next_url)
    path = parts.path
    marker = "/api/"
    relative = path.split(marker, 1)[1] if marker in path else endpoint.split("?", 1)[0]
    query = rest_query(**dict(parse_qsl(parts.query, keep_blank_values=True)))
    return f"{relative}?{query}" if query else relative


async def rest_paginate(
    nautobot: Any, endpoint: str, *, max_pages: int = MAX_REST_PAGES
) -> list[dict[str, Any]]:
    """Follow ``next`` until exhausted (bounded) and return all ``results``."""
    results: list[dict[str, Any]] = []
    current = endpoint
    for _ in range(max_pages):
        response = await nautobot.rest_request(endpoint=current, method="GET")
        if not isinstance(response, dict):
            break
        results.extend(response.get("results") or [])
        next_url = response.get("next")
        if not next_url:
            break
        current = _next_endpoint(str(next_url), current)
    return results
