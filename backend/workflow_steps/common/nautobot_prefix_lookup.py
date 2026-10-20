"""Prefix lookups shared by the Nautobot IP steps (Get Next Free IP, Add IP to Nautobot).

The functions take a plain ``rest_get(endpoint)`` callable so they work with a service plus
credentials as well as with ``CredentialsBoundNautobotClient``.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable
from typing import Any

from models.failure import FailureInfo
from services.nautobot.common.rest import rest_query
from services.nautobot.common.validators import is_valid_uuid

RestGet = Callable[[str], Awaitable[Any]]

_CONTAINING_PAGE = 200


class LookupFailure(Exception):
    """A lookup that cannot continue; carries the device-error code and structured cause."""

    def __init__(self, code: str, message: str, failure: FailureInfo) -> None:
        super().__init__(message)
        self.code = code
        self.failure = failure


def not_found(code: str, message: str) -> LookupFailure:
    return LookupFailure(
        code, message, FailureInfo(phase="api", kind="not_found", hint="check_request")
    )


def more_than_one(body: Any, results: list[dict[str, Any]]) -> bool:
    """A second row in the list, or one the answer says exists on another page."""
    if len(results) > 1 or (isinstance(body, dict) and body.get("next")):
        return True
    count = body.get("count") if isinstance(body, dict) else None
    return isinstance(count, int) and count > len(results)


def uuid_or_invalid(value: Any) -> str:
    """An id that is interpolated into a request path must be a UUID."""
    text = str(value or "")
    if not is_valid_uuid(text.lower()):
        raise LookupFailure(
            "invalid_response",
            "Nautobot answered with an id that is not a UUID",
            FailureInfo(phase="api", kind="invalid_response"),
        )
    return text


def list_results(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise LookupFailure(
            "invalid_response",
            "Nautobot answered with an unexpected body",
            FailureInfo(phase="api", kind="invalid_response"),
        )
    return [item for item in body.get("results") or [] if isinstance(item, dict)]


def _prefix_length(text: str) -> int | None:
    try:
        return ipaddress.ip_network(text, strict=False).prefixlen
    except ValueError:
        return None


async def find_containing_prefix(
    rest_get: RestGet,
    address: str,
    namespace_id: str,
    *,
    namespace_label: str,
) -> tuple[str, str]:
    """``(prefix_id, prefix)`` of the most specific prefix in the namespace holding *address*."""
    query = rest_query(
        contains=address, namespace=namespace_id, limit=_CONTAINING_PAGE, format="json"
    )
    body = await rest_get(f"ipam/prefixes/?{query}")
    best: tuple[int, str, str] | None = None
    for item in list_results(body):
        text = str(item.get("prefix") or "")
        length = _prefix_length(text)
        if length is None:
            continue
        if best is None or length > best[0]:
            best = (length, text, uuid_or_invalid(item.get("id")))
    if best is None:
        raise not_found(
            "prefix_not_found",
            f"No prefix contains {address} in namespace {namespace_label!r}",
        )
    return best[2], best[1]
