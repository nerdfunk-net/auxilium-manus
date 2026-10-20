"""Nautobot REST lookups for get-next-free-ip: namespace -> prefix id -> available IPs."""

from __future__ import annotations

import ipaddress
from typing import Any

from models.failure import FailureInfo
from services.nautobot.client import NautobotService
from services.nautobot.common.rest import rest_query
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.credentials import NautobotCredentials

AVAILABLE_IPS_CAP = 1000
_CONTAINING_PAGE = 200


class LookupFailure(Exception):
    """A lookup that cannot continue; carries the device-error code and structured cause."""

    def __init__(self, code: str, message: str, failure: FailureInfo) -> None:
        super().__init__(message)
        self.code = code
        self.failure = failure


def _not_found(code: str, message: str) -> LookupFailure:
    return LookupFailure(
        code, message, FailureInfo(phase="api", kind="not_found", hint="check_request")
    )


def _more_than_one(body: Any, results: list[dict[str, Any]]) -> bool:
    """A second row in the list, or one the answer says exists on another page."""
    if len(results) > 1 or (isinstance(body, dict) and body.get("next")):
        return True
    count = body.get("count") if isinstance(body, dict) else None
    return isinstance(count, int) and count > len(results)


def _uuid_or_invalid(value: Any) -> str:
    """An id that is interpolated into a request path must be a UUID."""
    text = str(value or "")
    if not is_valid_uuid(text.lower()):
        raise LookupFailure(
            "invalid_response",
            "Nautobot answered with an id that is not a UUID",
            FailureInfo(phase="api", kind="invalid_response"),
        )
    return text


def _results(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise LookupFailure(
            "invalid_response",
            "Nautobot answered with an unexpected body",
            FailureInfo(phase="api", kind="invalid_response"),
        )
    return [item for item in body.get("results") or [] if isinstance(item, dict)]


async def resolve_namespace_id(
    service: NautobotService, credentials: NautobotCredentials, namespace: str
) -> str:
    """Namespace UUID from a name (``Global``); a UUID is used as it is."""
    if is_valid_uuid(namespace):
        return namespace
    body = await service.rest_request(
        endpoint=f"ipam/namespaces/?{rest_query(name=namespace, format='json')}",
        credentials=credentials,
        method="GET",
    )
    results = _results(body)
    if not results or not results[0].get("id"):
        raise _not_found("namespace_not_found", f"Namespace {namespace!r} not found in Nautobot")
    if _more_than_one(body, results):
        raise LookupFailure(
            "namespace_ambiguous",
            f"Namespace {namespace!r} matches more than one namespace in Nautobot",
            FailureInfo(phase="api", kind="ambiguous_match", hint="check_request"),
        )
    return _uuid_or_invalid(results[0]["id"])


async def resolve_prefix_id(
    service: NautobotService,
    credentials: NautobotCredentials,
    prefix: str,
    namespace_id: str,
    *,
    namespace_label: str,
) -> str:
    """The one prefix UUID for *prefix* in the namespace; none or several is a failure."""
    query = rest_query(prefix=prefix, namespace=namespace_id, format="json")
    body = await service.rest_request(
        endpoint=f"ipam/prefixes/?{query}",
        credentials=credentials,
        method="GET",
    )
    results = _results(body)
    if not results:
        raise _not_found(
            "prefix_not_found",
            f"Prefix {prefix} not found in namespace {namespace_label!r}",
        )
    if _more_than_one(body, results):
        raise LookupFailure(
            "prefix_ambiguous",
            f"Prefix {prefix} matches several prefixes in namespace {namespace_label!r}",
            FailureInfo(phase="api", kind="ambiguous_match", hint="check_request"),
        )
    return _uuid_or_invalid(results[0].get("id"))


def _prefix_length(text: str) -> int | None:
    try:
        return ipaddress.ip_network(text, strict=False).prefixlen
    except ValueError:
        return None


async def resolve_containing_prefix(
    service: NautobotService,
    credentials: NautobotCredentials,
    address: str,
    namespace_id: str,
    *,
    namespace_label: str,
) -> tuple[str, str]:
    """``(prefix_id, prefix)`` of the most specific prefix in the namespace holding *address*."""
    query = rest_query(
        contains=address, namespace=namespace_id, limit=_CONTAINING_PAGE, format="json"
    )
    body = await service.rest_request(
        endpoint=f"ipam/prefixes/?{query}", credentials=credentials, method="GET"
    )
    best: tuple[int, str, str] | None = None
    for item in _results(body):
        text = str(item.get("prefix") or "")
        length = _prefix_length(text)
        if length is None:
            continue
        if best is None or length > best[0]:
            best = (length, text, _uuid_or_invalid(item.get("id")))
    if best is None:
        raise _not_found(
            "prefix_not_found",
            f"No prefix contains {address} in namespace {namespace_label!r}",
        )
    return best[2], best[1]


async def fetch_available_ips(
    service: NautobotService,
    credentials: NautobotCredentials,
    prefix_id: str,
    *,
    limit: int,
) -> list[Any]:
    """Free addresses of the prefix as Nautobot lists them (``available-ips``)."""
    query = rest_query(limit=limit, format="json")
    body: Any = await service.rest_request(
        endpoint=f"ipam/prefixes/{prefix_id}/available-ips/?{query}",
        credentials=credentials,
        method="GET",
    )
    if not isinstance(body, list):
        raise LookupFailure(
            "invalid_response",
            "Nautobot answered available-ips with an unexpected body",
            FailureInfo(phase="api", kind="invalid_response"),
        )
    return body
