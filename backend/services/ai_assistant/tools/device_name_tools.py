"""``get_device_name_matches``: the same device under its Batfish and its Nautobot name.

Batfish names a device after the hostname in its config (``lab``); Nautobot uses the full name
(``LAB.local.zz``). The Batfish tools and ``get_device`` already accept either spelling, so the
model rarely needs this: it is the explicit lookup for "which name does the other system use" and
for a name that is ambiguous or not found (doc/AI_TOOL_CHAIN.md §33).

Offered only when the user can read both systems. A pure read: nothing is changed or reserved.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from nautobot_read.errors import EXPECTED_ERRORS
from nautobot_read.queries import dcim
from nautobot_read.vocabularies import AmbiguousNameError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.nautobot_query_reader import NautobotAccessError
from services.ai_assistant.node_names import resolve_node_names
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.batfish_tools import (
    BATFISH_READER_KEY,
    BatfishAccessError,
    BatfishInputError,
    BatfishReader,
    BatfishUnavailableError,
)
from services.ai_assistant.tools.nautobot_tools import NAUTOBOT_READER_KEY, NautobotQueryReader

DeviceName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=253,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/\-]*$",
    ),
]
BatfishName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class DeviceNameInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: DeviceName = Field(
        description=(
            "A device name as the user or either system spells it, e.g. 'LAB.local.zz' or 'lab'"
        )
    )
    network: BatfishName | None = Field(
        default=None,
        description=(
            "Batfish network, from list_batfish_networks; only needed when there are several"
        ),
    )
    snapshot: BatfishName | None = Field(
        default=None, description="Snapshot name; omit for the newest"
    )
    source_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.\-]+$",
        description="Batfish source id; only needed when several sources are configured",
    )


async def _choose(reader: BatfishReader, args: DeviceNameInput) -> tuple[str, str] | dict[str, Any]:
    """The Batfish (source, network) to look in, or a status saying what is missing."""
    sources = [args.source_id] if args.source_id else await reader.list_sources()
    if not sources:
        return {"status": "no_source"}
    if len(sources) > 1:
        return {"status": "source_required", "sources": sorted(sources)}
    source = sources[0]
    if args.network:
        return source, args.network
    networks = await reader.list_networks(source)
    if len(networks) == 1:
        return source, networks[0]
    return {"status": "network_required", "networks": sorted(networks)}


async def _batfish_side(ctx: ToolContext, args: DeviceNameInput) -> dict[str, Any]:
    reader: BatfishReader = ctx.extras[BATFISH_READER_KEY]
    try:
        chosen = await _choose(reader, args)
        if isinstance(chosen, dict):
            return chosen
        source, network = chosen
        listing = await reader.node_names(source, network, args.snapshot)
    except BatfishAccessError:
        return {"status": "no_access"}
    except BatfishInputError as exc:
        return {"status": "problem", "message": str(exc)}
    except BatfishUnavailableError:
        return {"status": "unavailable"}
    ctx.audit_refs.add(f"batfish:{source}/{network}")
    outcome = resolve_node_names([args.name], listing.names)
    if args.name in outcome.resolved:
        return {
            "status": "found",
            "node": outcome.resolved[args.name],
            "network": network,
            "snapshot": listing.snapshot,
            "snapshot_created": listing.snapshot_created,
        }
    if args.name in outcome.ambiguous:
        return {"status": "ambiguous", "candidates": list(outcome.ambiguous[args.name])}
    return {"status": "not_found", "close": list(outcome.unknown.get(args.name, ()))}


async def _nautobot_side(ctx: ToolContext, args: DeviceNameInput) -> dict[str, Any]:
    reader: NautobotQueryReader = ctx.extras[NAUTOBOT_READER_KEY]
    try:
        query_ctx = await reader.context()
        # Asked with the name as given only: a device in another domain must not stand in.
        return {"status": "found", "name": await dcim.device_name(query_ctx, args.name)}
    except NautobotAccessError:
        return {"status": "no_access"}
    except AmbiguousNameError as exc:  # the message lists the candidates with their ids
        return {"status": "ambiguous", "message": str(exc)}
    except EXPECTED_ERRORS as exc:  # written for the model: says what was tried and what matched
        return {"status": "not_found", "message": str(exc)}


_NOTE = (
    "Batfish names a device after the hostname in its config (lower case, usually without the "
    "domain); Nautobot uses the full name. The Batfish tools and get_device accept either; use "
    "the 'node' value for Batfish and the 'name' value for Nautobot when quoting results."
)


async def _get_device_name_matches(ctx: ToolContext, args: DeviceNameInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    result = {
        "asked": args.name,
        "batfish": await _batfish_side(ctx, args),
        "nautobot": await _nautobot_side(ctx, args),
        "note": _NOTE,
    }
    return ToolOutput(json.dumps(ctx.redactor.redact_data(result), indent=1))


def build_device_name_tools() -> list[Tool]:
    """Offered by the surface only when the user can read both Batfish and Nautobot."""
    return [
        Tool(
            "get_device_name_matches",
            "Find one device under both names: the node name Batfish uses (the config hostname, "
            "for example 'lab') and the device name Nautobot uses (the full name, for example "
            "'LAB.local.zz'). Use it when a name is not found in one system, when asked which "
            "name the other system uses, or to settle an ambiguous short name (the result "
            "lists the candidates; never guess between them). Needs the inventory data switch.",
            DeviceNameInput,
            _get_device_name_matches,
        )
    ]
