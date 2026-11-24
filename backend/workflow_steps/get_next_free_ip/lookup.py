"""Nautobot REST lookups for get-next-free-ip: prefix id -> available IPs.

The namespace is resolved through the shared service (``DeviceCommonService``), like the sibling
steps do (W5-15).
"""

from __future__ import annotations

from typing import Any

from models.failure import FailureInfo
from services.nautobot.common.rest import rest_query
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
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


async def resolve_prefix_id(
    client: CredentialsBoundNautobotClient,
    prefix: str,
    namespace_id: str,
    *,
    namespace_label: str,
) -> str:
    """The one prefix UUID for *prefix* in the namespace; none or several is a failure."""
    query = rest_query(prefix=prefix, namespace=namespace_id, format="json")
    body = await client.rest_request(endpoint=f"ipam/prefixes/?{query}", method="GET")
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
    client: CredentialsBoundNautobotClient,
    address: str,
    namespace_id: str,
    *,
    namespace_label: str,
) -> tuple[str, str]:
    """``(prefix_id, prefix)`` of the most specific prefix in the namespace holding *address*."""

    async def rest_get(endpoint: str) -> Any:
        return await client.rest_request(endpoint=endpoint, method="GET")

    return await find_containing_prefix(
        rest_get, address, namespace_id, namespace_label=namespace_label
    )


async def fetch_available_ips(
    client: CredentialsBoundNautobotClient,
    prefix_id: str,
    *,
    limit: int,
) -> list[Any]:
    """Free addresses of the prefix as Nautobot lists them (``available-ips``)."""
    query = rest_query(limit=limit, format="json")
    body: Any = await client.rest_request(
        endpoint=f"ipam/prefixes/{prefix_id}/available-ips/?{query}", method="GET"
    )
    if not isinstance(body, list):
        raise LookupFailure(
            "invalid_response",
            "Nautobot answered available-ips with an unexpected body",
            FailureInfo(phase="api", kind="invalid_response"),
        )
    return body
