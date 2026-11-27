"""Nautobot lookups for get-next-free-ip that the shared service does not offer.

The namespace, the strict prefix lookup and the ``available-ips`` read go through
``DeviceCommonService`` (W5-15); only the containing-prefix search for a bare address stays here.
"""

from __future__ import annotations

from typing import Any

from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from workflow_steps.common.nautobot_prefix_lookup import LookupFailure, find_containing_prefix

__all__ = ["AVAILABLE_IPS_CAP", "LookupFailure"]

AVAILABLE_IPS_CAP = 1000


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
