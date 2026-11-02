"""Virtual chassis queries (a Cisco stack: several member devices behind one master's IP).

Shared by the assistant / MCP tools and by the ``get-virtual-chassis`` workflow step. The step
imports ``fetch_virtual_chassis``, ``pick_master`` and ``member_record`` from here, so the
GraphQL selection and the shape of a member record exist once.
"""

from __future__ import annotations

from typing import Any

from nautobot_read.client import GraphQLClient, NautobotError
from nautobot_read.context import QueryContext
from nautobot_read.queries.common import DEFAULT_LIMIT, check_paging, envelope
from nautobot_read.vocabularies import VIRTUAL_CHASSIS_SPEC, AmbiguousNameError
from nautobot_read.vocabulary import UUID_PATTERN, UnknownNameError, Vocabulary

MEMBER_SELECTION = """
      id
      name
      serial
      vc_position
      vc_priority
      device_type {
        model
      }
      platform {
        name
        network_driver
      }
      primary_ip4 {
        address
      }
      vc_master_for {
        id
        name
      }
"""
VC_SELECTION = f"id name members {{{MEMBER_SELECTION}    }}"

_ALL_QUERY = f"""
query VirtualChassis {{
  virtual_chassis {{
    {VC_SELECTION}
  }}
}}
"""


async def fetch_virtual_chassis(client: GraphQLClient) -> list[dict[str, Any]]:
    """Every virtual chassis with its members.

    Not paged: a stack has at most a handful of members and the workflow step wants them all.
    Raises ``NautobotError`` when the response carries no ``virtual_chassis`` list. The message
    is fixed: whatever Nautobot reported in ``errors`` must not reach a run log or the model.
    """
    data = await client.graphql(_ALL_QUERY, {})
    chassis = data.get("virtual_chassis")
    if chassis is None:
        raise NautobotError("Nautobot returned no virtual chassis list.")
    return [vc for vc in chassis if isinstance(vc, dict)]


def position_key(member: dict[str, Any]) -> tuple[bool, int, str]:
    """Sort key: members with a stack position first (ascending), then by name."""
    position = member.get("vc_position")
    return (
        not isinstance(position, int),
        position if isinstance(position, int) else 0,
        str(member.get("name") or ""),
    )


def ordered_members(vc: dict[str, Any]) -> list[dict[str, Any]]:
    """The members of one raw ``virtual_chassis`` object, sorted by position."""
    raw = vc.get("members")
    return sorted((m for m in raw if isinstance(m, dict)) if isinstance(raw, list) else [],
                  key=position_key)


def pick_master(members: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The member flagged ``vc_master_for``; else the one with the lowest position."""
    for member in members:
        if member.get("vc_master_for"):
            return member
    ordered = sorted(members, key=position_key)
    return ordered[0] if ordered else None


def address_of(member: dict[str, Any] | None) -> str | None:
    """The member's primary IPv4 as ``address/prefix``, if it has one."""
    if member is None:
        return None
    ip = member.get("primary_ip4")
    address = ip.get("address") if isinstance(ip, dict) else None
    return str(address) if address else None


def device_type_model(member: dict[str, Any]) -> str | None:
    device_type = member.get("device_type")
    model = device_type.get("model") if isinstance(device_type, dict) else None
    return str(model) if model else None


def member_record(member: dict[str, Any], *, master: dict[str, Any] | None) -> dict[str, Any]:
    """One member as a flat record (the step adds its own index key on top)."""
    return {
        "id": member.get("id"),
        "name": str(member.get("name") or ""),
        "position": member.get("vc_position"),
        "priority": member.get("vc_priority"),
        "serial": member.get("serial") or None,
        "device_type": device_type_model(member),
        "primary_ip4": address_of(member),
        "is_master": member is master,
    }


def stack_item(vc: dict[str, Any]) -> dict[str, Any]:
    """One stack for the tools: identity, master and the members in stack order."""
    members = ordered_members(vc)
    master = pick_master(members)
    return {
        "id": vc.get("id"),
        "name": vc.get("name"),
        "member_count": len(members),
        "master": master.get("name") if master else None,
        "master_primary_ip4": address_of(master),
        "members": [m["name"] for m in members],
    }


async def list_virtual_chassis(
    ctx: QueryContext,
    *,
    name_contains: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Virtual chassis (stacks), one compact row each, optionally by part of the name."""
    check_paging(limit, offset)
    filters: dict[str, list[str]] = {}
    applied: dict[str, Any] = {}
    if name_contains:
        filters["name__ic"], applied["name_contains"] = [name_contains], name_contains
    page = await ctx.client.list_page(
        "virtual_chassis", VC_SELECTION, filters, limit=limit, offset=offset
    )
    items = [stack_item(row) for row in page.items]
    return envelope(items, page, offset=offset, applied_filters=applied)


def _stack_name(vocabulary: Vocabulary, text: str) -> str:
    """The stored spelling for ``text``: an exact spelling wins, a case-only match must be unique.

    ``Vocabulary.resolve`` keeps one spelling when two names differ only by case, so a stack
    could not be fetched by its own name; an exact match is therefore taken first and a
    case-insensitive match that fits several stacks is reported, not guessed.
    """
    if text in vocabulary.names:
        return text
    folded = [name for name in vocabulary.names if name.casefold() == text.casefold()]
    if len(folded) > 1:
        raise AmbiguousNameError(
            f"'{text}' matches {len(folded)} virtual chassis: {', '.join(folded)}. "
            "Retry with the exact name or the id."
        )
    return vocabulary.resolve(text)


async def get_virtual_chassis(ctx: QueryContext, *, virtual_chassis: str) -> dict[str, Any]:
    """One stack with every member (position, priority, serial, type, address, master flag).

    The row is checked against what was asked for: a filter Nautobot accepts but ignores
    would otherwise return an unrelated stack, with its addresses, as the answer.
    """
    text = virtual_chassis.strip()
    if UUID_PATTERN.match(text):
        wanted = text.lower()
        filters = {"id": [wanted]}

        def is_wanted(row: dict[str, Any]) -> bool:
            return str(row.get("id") or "").lower() == wanted
    else:
        name = _stack_name(await ctx.vocabularies.get(VIRTUAL_CHASSIS_SPEC), text)
        filters = {"name": [name]}

        def is_wanted(row: dict[str, Any]) -> bool:
            return row.get("name") == name

    # Two rows, not one: a second match must be seen to be reported.
    page = await ctx.client.list_page("virtual_chassis", VC_SELECTION, filters, limit=2, offset=0)
    rows = [row for row in page.items if is_wanted(row)]
    if not rows:
        raise UnknownNameError(
            f"No virtual chassis '{text}'. Use list_virtual_chassis to see the stacks."
        )
    if len(rows) > 1:
        ids = ", ".join(str(row.get("id")) for row in rows)
        raise AmbiguousNameError(
            f"'{text}' matches {len(rows)} virtual chassis (ids {ids}). Retry with the id."
        )
    row = rows[0]
    members = ordered_members(row)
    master = pick_master(members)
    item = stack_item(row)
    item["members"] = [member_record(m, master=master) for m in members]
    return item
