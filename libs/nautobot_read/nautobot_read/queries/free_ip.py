"""Next free IP addresses of a prefix (read-only; nothing is reserved).

The same lookup as the workflow step ``get-next-free-ip``: find the one prefix, read its
``available-ips`` from the REST API (GraphQL has no equivalent), keep the addresses at or after
``network address + start_offset``. The step's code is not imported (the library depends on
neither ``backend`` nor ``workflow_steps``), so the few pure helpers are repeated here.
"""

from __future__ import annotations

import ipaddress
from typing import Any

from nautobot_read import networks
from nautobot_read.client import NautobotError
from nautobot_read.context import QueryContext
from nautobot_read.networks import InvalidInputError
from nautobot_read.vocabularies import NAMESPACES_SPEC, AmbiguousNameError
from nautobot_read.vocabulary import UUID_PATTERN, UnknownNameError

MAX_COUNT = 20
MAX_START_OFFSET = 1_000_000
# Free addresses read from Nautobot per request; a shortage beyond it is not proof of a full prefix.
AVAILABLE_IPS_CAP = 1000
# Prefixes holding one address; more than this is not a lookup a model should be guessing at.
MAX_CANDIDATES = 200
PREFIX_SELECTION = "id prefix namespace { name }"
NOTE = (
    "Read-only: nothing is reserved in Nautobot, so another user, run or workflow can be given "
    "the same address until it exists there."
)

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


def _is_bare_address(text: str) -> bool:
    return "/" not in text


def _free_addresses(available: list[Any], network: Network, start_offset: int) -> list[str]:
    """Bare free addresses inside ``network`` at or after ``network + start_offset``.

    Entries that are not ``{"address": "<ip>/<len>"}`` or lie outside the prefix are ignored.
    """
    first = int(network.network_address) + start_offset
    found: list[str] = []
    for item in available:
        if not isinstance(item, dict):
            continue
        try:
            address = ipaddress.ip_address(str(item.get("address") or "").split("/", 1)[0].strip())
        except ValueError:
            continue
        if address.version == network.version and address in network and int(address) >= first:
            found.append(str(address))
    return found


def _namespace_of(row: dict[str, Any]) -> str:
    return (row.get("namespace") or {}).get("name") or ""


async def _find_prefix(
    ctx: QueryContext, value: str, namespace: str | None
) -> tuple[str, Network, str]:
    """``(prefix_id, network, namespace)`` of the one prefix meant by ``value``.

    ``value`` is a prefix in CIDR notation (host bits are cleared, like the workflow step) or a
    bare address, which means the most specific prefix that contains it.
    """
    text = value.strip()
    bare = _is_bare_address(text)
    filters: dict[str, list[str]] = {}
    if namespace:
        filters["namespace"] = [(await ctx.vocabularies.get(NAMESPACES_SPEC)).resolve(namespace)]
    wanted = networks.address(text) if bare else networks.prefix(text)
    filters["contains" if bare else "prefix"] = [wanted]
    page = await ctx.client.list_page(
        "prefixes", PREFIX_SELECTION, filters, limit=MAX_CANDIDATES, offset=0
    )
    if page.has_more:
        raise NautobotError(
            f"More than {MAX_CANDIDATES} prefixes contain {text}; give the prefix in CIDR "
            "notation instead."
        )
    # The most specific prefix per namespace (an address may sit in a /8 and a /24).
    best: dict[str, tuple[int, str, Network]] = {}
    for row in page.items:
        try:
            network = ipaddress.ip_network(str(row.get("prefix")), strict=False)
        except ValueError:
            continue
        if not bare and str(network) != wanted:
            continue  # defensive: the exact filter should not return another prefix
        name = _namespace_of(row)
        if name not in best or network.prefixlen > best[name][0]:
            best[name] = (network.prefixlen, str(row.get("id") or ""), network)
    where = f" in namespace '{namespace}'" if namespace else ""
    if not best:
        what = f"contains {text}" if bare else wanted
        raise UnknownNameError(
            f"No prefix {what} in Nautobot{where}. Check it with list_prefixes."
        )
    if len(best) > 1:
        raise AmbiguousNameError(
            f"{text} exists in {len(best)} namespaces: {', '.join(sorted(best))}. "
            "Retry with the namespace."
        )
    ((name, (_, prefix_id, network)),) = best.items()
    return prefix_id, network, name


async def get_next_free_ip(
    ctx: QueryContext,
    *,
    prefix: str,
    namespace: str | None = None,
    count: int = 1,
    start_offset: int = 1,
) -> dict[str, Any]:
    """The next ``count`` free addresses of a prefix, counted from the network address."""
    if not 1 <= count <= MAX_COUNT:
        raise InvalidInputError(f"count must be between 1 and {MAX_COUNT}, not {count}.")
    if not 0 <= start_offset <= MAX_START_OFFSET:
        raise InvalidInputError(
            f"start_offset must be between 0 and {MAX_START_OFFSET}, not {start_offset}."
        )
    prefix_id, network, namespace_name = await _find_prefix(ctx, prefix, namespace)
    if not UUID_PATTERN.match(prefix_id):
        # The id goes into a request path: it must be what Nautobot's ids look like.
        raise NautobotError("Nautobot answered with a prefix id that is not a UUID.")
    wanted = start_offset + count
    limit = min(wanted, AVAILABLE_IPS_CAP)
    available = await ctx.client.rest_get(
        f"ipam/prefixes/{prefix_id}/available-ips/?limit={limit}&format=json"
    )
    if not isinstance(available, list):
        raise NautobotError("Nautobot answered with an unexpected body for the free addresses.")
    window_cut = wanted > AVAILABLE_IPS_CAP and len(available) >= AVAILABLE_IPS_CAP
    addresses = _free_addresses(available, network, start_offset)[:count]
    note = NOTE
    if len(addresses) < count:
        note += (
            f" Only {len(addresses)} free address(es) found from offset {start_offset}: "
            + (
                f"only the first {AVAILABLE_IPS_CAP} free addresses are read per request, so "
                "this does not show that the prefix is full (lower start_offset or count)."
                if window_cut
                else "the prefix is full from there."
            )
        )
    return {
        "prefix": str(network),
        "namespace": namespace_name,
        "start_offset": start_offset,
        "requested": count,
        "returned": len(addresses),
        "complete": len(addresses) == count,
        "addresses": addresses,
        "note": note,
    }
