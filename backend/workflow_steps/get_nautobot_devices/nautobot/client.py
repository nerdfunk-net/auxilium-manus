"""Minimal async Nautobot GraphQL client.

Credentials are passed per-call — no global state, no env-var dependency.
"""

from __future__ import annotations

from typing import Any

import httpx


async def graphql_query(
    nautobot_url: str,
    nautobot_token: str,
    query: str,
    variables: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    headers = {
        "Authorization": f"Token {nautobot_token}",
        "Content-Type": "application/json",
    }
    url = f"{nautobot_url.rstrip('/')}/api/graphql/"
    payload = {"query": query, "variables": variables}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()
