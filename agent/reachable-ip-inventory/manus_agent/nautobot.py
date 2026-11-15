"""Read the IP prefixes that carry a tag from Nautobot's GraphQL API (read only).

The tag travels as a GraphQL *variable*, never inside the query text. Errors are fixed texts:
neither the token nor Nautobot's answer is ever echoed (a message ends up in the run view).
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from manus_agent.hostpolicy import SafeResolver
from manus_agent.inventory_config import NautobotSettings

logger = logging.getLogger(__name__)

PAGE_SIZE = 200
_QUERY = (
    "query ($tag: [String], $limit: Int, $offset: Int) "
    "{ prefixes(tags: $tag, limit: $limit, offset: $offset) { prefix } }"
)


class NautobotError(RuntimeError):
    """Nautobot could not be read; the message is fixed text."""


async def _page(
    session: aiohttp.ClientSession, settings: NautobotSettings, tag: str, offset: int
) -> list[str]:
    payload = {"query": _QUERY, "variables": {"tag": [tag], "limit": PAGE_SIZE, "offset": offset}}
    try:
        async with session.post(
            f"{settings.url}/api/graphql/",
            json=payload,
            headers={"Authorization": f"Token {settings.token}", "Accept": "application/json"},
            ssl=None if settings.verify_ssl else False,
            allow_redirects=False,  # a redirect would forward the token to another host
        ) as response:
            if response.status != 200:
                logger.warning("Nautobot GraphQL answered HTTP %s", response.status)
                raise NautobotError(f"Nautobot answered HTTP {response.status} to the prefix query")
            body: Any = await response.json(content_type=None)
    except TimeoutError as exc:
        raise NautobotError("Nautobot did not answer in time") from exc
    except (aiohttp.ClientError, ValueError) as exc:
        raise NautobotError("Nautobot could not be reached or answered with invalid data") from exc

    if not isinstance(body, dict):
        raise NautobotError("Nautobot's answer is not a JSON object")
    if body.get("errors"):
        # Partial data must never be mistaken for "no prefixes".
        raise NautobotError("Nautobot's GraphQL API reported an error for the prefix query")
    rows = (body.get("data") or {}).get("prefixes") if isinstance(body.get("data"), dict) else None
    if not isinstance(rows, list):
        raise NautobotError("Nautobot's answer has no prefix list")
    prefixes: list[str] = []
    for row in rows:
        value = row.get("prefix") if isinstance(row, dict) else None
        if not isinstance(value, str) or not value:
            raise NautobotError("Nautobot returned a prefix row without a prefix")
        prefixes.append(value)
    return prefixes


async def fetch_prefixes_by_tag(settings: NautobotSettings, tag: str) -> list[str]:
    """Every prefix (CIDR text) tagged *tag*; more than ``max_prefixes`` is an error."""
    timeout = aiohttp.ClientTimeout(total=settings.timeout_seconds)
    found: list[str] = []
    # SafeResolver: the token never goes to an address the host policy blocks.
    connector = aiohttp.TCPConnector(resolver=SafeResolver())
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        offset = 0
        while True:
            page = await _page(session, settings, tag, offset)
            found.extend(page)
            if len(found) > settings.max_prefixes:
                raise NautobotError(
                    f"more than {settings.max_prefixes} prefixes carry the tag "
                    "(the limit of this agent, nautobot.max_prefixes)"
                )
            if len(page) < PAGE_SIZE:
                return found
            offset += PAGE_SIZE
