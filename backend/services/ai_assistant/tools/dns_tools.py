"""``get_dns_lookup``: what the DNS says for a name or an IP address (doc/AI_TOOL_CHAIN.md §50).

"Which name belongs to 1.1.1.1?" is a reverse (PTR) lookup, "what IP does LAB.local.zz resolve
to?" a forward one. The answer is live, from the backend host's resolver, and is not what
Nautobot or Batfish document. A pure read, but a DNS query leaves the building, so the name or
address is checked by ``dns_policy`` first (forward lookups only under the operator's suffixes)
and the answer is class B data: the inventory and addresses switches are checked before any
lookup.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.audit import log_dns_lookup
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.dns_policy import DnsPolicyError, forward_name, reverse_address
from services.ai_assistant.dns_resolver import DnsAnswer, DnsResolver
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput

# Key of the ``DnsResolver`` in ``ToolContext.extras``; the surface builder puts it there.
DNS_RESOLVER_KEY = "dns_resolver"

_RESOLVER = "the backend host's system resolver"
_NOTE = (
    "A live answer from the backend host's resolver, not stored data and not necessarily what "
    "the device itself would get from its own DNS server. It carries no TTL. not_found means "
    "no such name or record, never proof that a host does not exist; unavailable means the "
    "resolver did not answer. Nautobot and Batfish show what is documented: compare them when "
    "the two differ."
)


class DnsLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ] = Field(
        description=(
            "An IPv4/IPv6 address for a reverse lookup (which name belongs to it), or a fully "
            "qualified host name for a forward lookup (which addresses it resolves to)"
        )
    )


def _is_address(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


async def _lookup(resolver: DnsResolver, query: str) -> dict[str, Any]:
    reverse = _is_address(query)
    try:
        if reverse:
            address = str(reverse_address(query))
            answer: DnsAnswer = await resolver.reverse(address)
        else:
            address = forward_name(query, resolver.allowed_suffixes)
            answer = await resolver.forward(address)
    except DnsPolicyError as exc:
        return {
            "kind": "reverse" if reverse else "forward",
            "status": "not_allowed",
            "message": str(exc),
        }
    if reverse:
        return {
            "kind": "reverse",
            "asked": address,
            "status": answer.status,
            "names": list(answer.values),
        }
    if answer.status == "outside_allowed_domain":
        return {
            "kind": "forward",
            "asked": address,
            "status": "not_allowed",
            "canonical_name": answer.canonical_name,
            "message": "The name is an alias for a name outside the allowed domains; "
            "no addresses are reported. Tell the user; do not look up the target.",
        }
    result: dict[str, Any] = {
        "kind": "forward",
        "asked": address,
        "status": answer.status,
        "addresses": list(answer.values),
    }
    if answer.canonical_name:
        result["canonical_name"] = answer.canonical_name
    return result


async def _get_dns_lookup(ctx: ToolContext, args: DnsLookupInput) -> ToolOutput:
    # Both switches first, so a refusal cannot be told from an answer by what it did.
    for data_class in (DataClass.INVENTORY, DataClass.ADDRESSES):
        if not ctx.sharing.allows(data_class):
            return ToolOutput(json.dumps(not_shared_marker(data_class), indent=1))
    resolver: DnsResolver = ctx.extras[DNS_RESOLVER_KEY]
    result = await _lookup(resolver, args.query)
    log_dns_lookup(query=args.query, status=str(result.get("status")))
    result["resolver"] = _RESOLVER
    result["note"] = _NOTE
    return ToolOutput(json.dumps(ctx.redactor.redact_data(result), indent=1))


def build_dns_tools() -> list[Tool]:
    """Offered by the surface only when the operator enabled DNS lookups."""
    return [
        Tool(
            "get_dns_lookup",
            "Ask DNS. Give an IP address to find the name that belongs to it (reverse lookup), "
            "or a fully qualified host name such as 'LAB.local.zz' to find the IP addresses it "
            "resolves to. Use it for 'which name has this IP' and 'what IP does this name "
            "have in DNS'. Name lookups work only under the domains the operator allows; the "
            "result says so when a name is refused. Needs the inventory and addresses data "
            "switches.",
            DnsLookupInput,
            _get_dns_lookup,
        )
    ]
