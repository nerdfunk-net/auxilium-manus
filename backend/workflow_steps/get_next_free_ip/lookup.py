"""Nautobot REST lookups for get-next-free-ip: namespace -> prefix id -> available IPs."""

from __future__ import annotations

from typing import Any

from models.failure import FailureInfo
from services.nautobot.client import NautobotService
from services.nautobot.common.rest import rest_query
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.credentials import NautobotCredentials
from workflow_steps.common.nautobot_prefix_lookup import (
    LookupFailure,
    find_containing_prefix,
    list_results,
    more_than_one,
    not_found,
    uuid_or_invalid,
)

__all__ = ["AVAILABLE_IPS_CAP", "LookupFailure"]

AVAILABLE_IPS_CAP = 1000


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
    results = list_results(body)
    if not results or not results[0].get("id"):
        raise not_found("namespace_not_found", f"Namespace {namespace!r} not found in Nautobot")
    if more_than_one(body, results):
        raise LookupFailure(
            "namespace_ambiguous",
            f"Namespace {namespace!r} matches more than one namespace in Nautobot",
            FailureInfo(phase="api", kind="ambiguous_match", hint="check_request"),
        )
    return uuid_or_invalid(results[0]["id"])


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
    results = list_results(body)
    if not results:
        raise not_found(
            "prefix_not_found",
            f"Prefix {prefix} not found in namespace {namespace_label!r}",
        )
    if more_than_one(body, results):
        raise LookupFailure(
            "prefix_ambiguous",
            f"Prefix {prefix} matches several prefixes in namespace {namespace_label!r}",
            FailureInfo(phase="api", kind="ambiguous_match", hint="check_request"),
        )
    return uuid_or_invalid(results[0].get("id"))


async def resolve_containing_prefix(
    service: NautobotService,
    credentials: NautobotCredentials,
    address: str,
    namespace_id: str,
    *,
    namespace_label: str,
) -> tuple[str, str]:
    """``(prefix_id, prefix)`` of the most specific prefix in the namespace holding *address*."""

    async def rest_get(endpoint: str) -> Any:
        return await service.rest_request(endpoint=endpoint, credentials=credentials, method="GET")

    return await find_containing_prefix(
        rest_get, address, namespace_id, namespace_label=namespace_label
    )


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
