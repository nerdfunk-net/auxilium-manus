"""Nautobot DCIM / IPAM reads for Ask the Net (doc/AI_TOOL_CHAIN.md, "Nautobot tools").

The queries are the shared ``nautobot_read`` library (also behind ``mcp/nautobot``). This module
adds what only the assistant needs: input models, the opt-in gates and redaction.

Pure reads, as the calling user. Data sharing (doc/ai_integration/AI_ASSISTANT.md §4):

- Vocabulary tools (roles, statuses, tags, device types, platforms, namespaces, location types)
  describe how the instance is organised, not its devices: always available.
- Locations: the tree is always available; free text, addresses and coordinates need the
  inventory switch.
- Devices need the inventory switch; addresses, serials and interfaces need the addresses switch
  on top. Without it those fields are left out and ``withheld_fields`` says which setting
  releases them.
- IP addresses, prefixes and the next free address need the addresses switch: the whole tool
  answers with the not-shared marker *before* anything is sent to Nautobot, so even a count
  cannot leak.

A field the rules below do not name is never sent (fail closed), the same stance as
``data_sharing.filter_nautobot_attributes``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Any, Protocol

from nautobot_read.context import QueryContext
from nautobot_read.errors import EXPECTED_ERRORS
from nautobot_read.queries import dcim, free_ip, ipam, organization
from nautobot_read.queries.common import ContentType
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.data_sharing import DataClass, SharingPolicy, not_shared_marker
from services.ai_assistant.nautobot_query_reader import NautobotAccessError
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput

# Key of the ``NautobotQueryReader`` in ``ToolContext.extras``; the surface builder puts it there.
NAUTOBOT_READER_KEY = "nautobot_query_reader"
# Rows per page offered to the model. Smaller than the library's 200: a page must fit the tool
# output cap (tools/base.py) or it is cut in the middle of a row.
DEFAULT_PAGE = 20
MAX_PAGE = 100
MAX_FIELD_CHARS = 500

ALWAYS = "always"
NEVER = "never"
Rule = DataClass | str

_NO_ACCESS = ToolOutput(
    "You cannot read Nautobot data here (missing permission or no usable Nautobot source).",
    is_error=True,
)


class NautobotQueryReader(Protocol):
    async def context(self) -> QueryContext: ...


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Page = Annotated[int, Field(ge=1, le=MAX_PAGE)]
Skip = Annotated[int, Field(ge=0, le=100_000)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoInput(_Input):
    pass


class ContentTypeInput(_Input):
    content_type: ContentType = Field(
        default="dcim.device", description="Object type the names apply to, e.g. 'dcim.device'."
    )


class ListLocationsInput(_Input):
    location_type: Name | None = Field(None, description="Location type, e.g. 'Country'.")
    parent: Name | None = Field(
        None,
        description="Only direct children of this location (name, 'Parent → Name' path or id).",
    )
    status: Name | None = Field(None, description="Status name, e.g. 'Active'.")
    tag: Name | None = Field(None, description="Tag name.")
    name_contains: Name | None = Field(None, description="Part of the location name.")
    limit: Page = DEFAULT_PAGE
    offset: Skip = 0


class GetLocationInput(_Input):
    location: Name = Field(description="Location name, 'Parent → Name' path or id.")


class ListDevicesInput(_Input):
    location: Name | None = Field(
        None, description="Location name, 'Parent → Name' path or id; includes child locations."
    )
    role: Name | None = Field(None, description="Device role, e.g. 'Network'. See list_roles.")
    status: Name | None = Field(None, description="Device status, e.g. 'Active'.")
    tag: Name | None = Field(None, description="Tag name.")
    device_type: Name | None = Field(None, description="Device type model. See list_device_types.")
    platform: Name | None = Field(None, description="Platform, e.g. 'Cisco IOS'.")
    name_contains: Name | None = Field(None, description="Part of the device name.")
    limit: Page = DEFAULT_PAGE
    offset: Skip = 0


class GetDeviceInput(_Input):
    device: Name = Field(description="Exact device name, or id.")


class ListIpAddressesInput(_Input):
    address: Name | None = Field(None, description="Exact address, e.g. '10.0.0.2/24'.")
    prefix: Name | None = Field(None, description="Only addresses inside this network.")
    device: Name | None = Field(None, description="Only addresses assigned to this device.")
    namespace: Name | None = Field(None, description="Namespace. See list_namespaces.")
    role: Name | None = Field(None, description="IP role, e.g. 'Loopback'.")
    status: Name | None = Field(None, description="IP status, e.g. 'Active'.")
    tag: Name | None = Field(None, description="Tag name.")
    dns_name_contains: Name | None = Field(None, description="Part of the DNS name.")
    limit: Page = DEFAULT_PAGE
    offset: Skip = 0


class ListPrefixesInput(_Input):
    prefix: Name | None = Field(None, description="Exact prefix in CIDR notation.")
    within: Name | None = Field(None, description="Prefixes inside this network, including it.")
    contains: Name | None = Field(None, description="Prefixes that contain this address.")
    location: Name | None = Field(
        None,
        description="Prefixes assigned to this location (name, path or id). Not verified to "
        "include prefixes of child locations.",
    )
    namespace: Name | None = Field(None, description="Namespace. See list_namespaces.")
    role: Name | None = Field(None, description="Prefix role.")
    status: Name | None = Field(None, description="Prefix status, e.g. 'Active'.")
    tag: Name | None = Field(None, description="Tag name.")
    limit: Page = DEFAULT_PAGE
    offset: Skip = 0


class NextFreeIpInput(_Input):
    prefix: Name = Field(
        description="The prefix in CIDR notation, e.g. '10.0.0.0/24'; or a single address, which "
        "means the most specific prefix that contains it."
    )
    namespace: Name | None = Field(
        None, description="Namespace, only needed when the prefix exists in several."
    )
    count: Annotated[int, Field(ge=1, le=free_ip.MAX_COUNT)] = 1
    start_offset: Annotated[int, Field(ge=0, le=free_ip.MAX_START_OFFSET)] = Field(
        1, description="Where the search starts, counted from the network address."
    )


# -- what each result field needs ------------------------------------------------------------

_LOCATION_RULES: Mapping[str, Rule] = {
    "id": ALWAYS,
    "name": ALWAYS,
    "path": ALWAYS,
    "location_type": ALWAYS,
    "status": ALWAYS,
    "parent": ALWAYS,
    "tags": ALWAYS,
    "children": ALWAYS,
    "description": DataClass.INVENTORY,
    "facility": DataClass.INVENTORY,
    "physical_address": DataClass.INVENTORY,
    "time_zone": DataClass.INVENTORY,
    "latitude": DataClass.INVENTORY,
    "longitude": DataClass.INVENTORY,
}
_DEVICE_RULES: Mapping[str, Rule] = {
    **dict.fromkeys(
        (
            "id", "name", "role", "status", "device_type", "manufacturer", "platform",
            "location", "tags", "rack", "tenant",
        ),
        DataClass.INVENTORY,
    ),
    **dict.fromkeys(
        (
            "primary_ip4", "primary_ip6", "serial", "asset_tag", "interfaces",
            "interfaces_truncated",
        ),
        DataClass.ADDRESSES,
    ),
    # Free text of unknown content: not shared at any setting.
    "comments": NEVER,
}


def _project(
    policy: SharingPolicy, item: Mapping[str, Any], rules: Mapping[str, Rule]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Keep the fields the user's opt-ins allow; report the rest and what would release it."""
    kept: dict[str, Any] = {}
    withheld: dict[str, str] = {}
    for key, value in item.items():
        rule = rules.get(key, NEVER)
        if rule == ALWAYS or (isinstance(rule, DataClass) and policy.allows(rule)):
            kept[key] = value
        elif isinstance(rule, DataClass):
            withheld[key] = not_shared_marker(rule)["not_shared"]
        else:
            withheld[key] = NEVER
    return kept, withheld


def _shape_items(rules: Mapping[str, Rule]) -> Callable[[SharingPolicy, dict[str, Any]], dict]:
    """A shaper for a list result: project every item, report withheld fields once."""

    def shape(policy: SharingPolicy, result: dict[str, Any]) -> dict[str, Any]:
        withheld: dict[str, str] = {}
        items = []
        for item in result["items"]:
            kept, dropped = _project(policy, item, rules)
            items.append(kept)
            withheld.update(dropped)
        return {**result, "items": items, **({"withheld_fields": withheld} if withheld else {})}

    return shape


def _shape_one(rules: Mapping[str, Rule]) -> Callable[[SharingPolicy, dict[str, Any]], dict]:
    def shape(policy: SharingPolicy, result: dict[str, Any]) -> dict[str, Any]:
        kept, withheld = _project(policy, result, rules)
        return {**kept, **({"withheld_fields": withheld} if withheld else {})}

    return shape


def _unchanged(_policy: SharingPolicy, result: dict[str, Any]) -> dict[str, Any]:
    return result


# -- plumbing --------------------------------------------------------------------------------

Query = Callable[..., Awaitable[dict[str, Any]]]
Shaper = Callable[[SharingPolicy, dict[str, Any]], dict[str, Any]]


def _cap(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS] + "…" if len(value) > MAX_FIELD_CHARS else value
    if isinstance(value, dict):
        return {k: _cap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v) for v in value]
    return value


def _tool(
    name: str,
    description: str,
    model: type[BaseModel],
    query: Query,
    *,
    gate: DataClass | None = None,
    shape: Shaper = _unchanged,
) -> Tool:
    """One tool: gate before any request, run the library query, shape, redact, cap."""

    async def handler(ctx: ToolContext, args: Any) -> ToolOutput:
        if gate is not None and not ctx.sharing.allows(gate):
            return ToolOutput(json.dumps(not_shared_marker(gate), indent=1))
        reader: NautobotQueryReader = ctx.extras[NAUTOBOT_READER_KEY]
        try:
            query_ctx = await reader.context()
            result = await query(query_ctx, **args.model_dump())
        except NautobotAccessError:
            return _NO_ACCESS
        except EXPECTED_ERRORS as exc:  # written for the model: closest and available names
            return ToolOutput(str(exc), is_error=True)
        shaped = _cap(ctx.redactor.redact_data(shape(ctx.sharing, result)))
        return ToolOutput(json.dumps(shaped, default=str, indent=1))

    return Tool(name, description, model, handler)


def build_nautobot_tools() -> tuple[Tool, ...]:
    """The Nautobot read tools; the surface offers them only with a ``NautobotQueryReader``."""
    return (
        _tool(
            "list_locations",
            "Nautobot locations (countries, regions, cities, sites ...), each with its path such "
            "as 'Germany → Berlin'. Filters combine with AND. An unknown name returns the "
            "closest and the available names.",
            ListLocationsInput,
            organization.list_locations,
            shape=_shape_items(_LOCATION_RULES),
        ),
        _tool(
            "get_location",
            "One Nautobot location with its parent and direct children.",
            GetLocationInput,
            organization.get_location,
            shape=_shape_one(_LOCATION_RULES),
        ),
        _tool(
            "list_location_types",
            "Nautobot location types and their hierarchy, for example Country > State > City.",
            NoInput,
            organization.list_location_types,
        ),
        _tool(
            "list_roles",
            "Role names in Nautobot for one object type (device, IP address, prefix ...). "
            "Words like 'router' may be a role, a device type or a platform here: check "
            "list_roles, list_device_types and list_platforms.",
            ContentTypeInput,
            organization.list_roles,
        ),
        _tool(
            "list_statuses",
            "Status names in Nautobot for one object type.",
            ContentTypeInput,
            organization.list_statuses,
        ),
        _tool(
            "list_tags",
            "Tag names in Nautobot that can be applied to one object type.",
            ContentTypeInput,
            organization.list_tags,
        ),
        _tool(
            "list_devices",
            "Nautobot devices (the documented inventory, not live state), filtered. Filters "
            "combine with AND; a location includes its child locations. Names are matched "
            "case-insensitively and an unknown name returns the closest and the available ones. "
            "Page with offset while has_more is true. Needs the inventory data switch.",
            ListDevicesInput,
            dcim.list_devices,
            gate=DataClass.INVENTORY,
            shape=_shape_items(_DEVICE_RULES),
        ),
        _tool(
            "get_device",
            "One Nautobot device by exact name or id, with rack, tenant and (if the user shares "
            "addresses) its interfaces and their IP addresses. If a name matches several "
            "devices the error lists them with their ids. Needs the inventory data switch.",
            GetDeviceInput,
            dcim.get_device,
            gate=DataClass.INVENTORY,
            shape=_shape_one(_DEVICE_RULES),
        ),
        _tool(
            "list_device_types",
            "Nautobot device type models with their manufacturer (valid values for the "
            "device_type filter).",
            NoInput,
            dcim.list_device_types,
        ),
        _tool(
            "list_platforms",
            "Nautobot platforms (for example 'Cisco IOS') with manufacturer and network driver.",
            NoInput,
            dcim.list_platforms,
        ),
        _tool(
            "list_ip_addresses",
            "Nautobot IP addresses (documented, not live), filtered; each shows its prefix, "
            "namespace and the device interfaces it is assigned to. Page with offset while "
            "has_more is true. Needs the addresses data switch.",
            ListIpAddressesInput,
            ipam.list_ip_addresses,
            gate=DataClass.ADDRESSES,
        ),
        _tool(
            "list_prefixes",
            "Nautobot IP prefixes (networks, documented), filtered: exact, inside a network, "
            "or containing an address. A location filter may not include child locations. Page "
            "with offset while has_more is true. Needs the addresses data switch.",
            ListPrefixesInput,
            ipam.list_prefixes,
            gate=DataClass.ADDRESSES,
        ),
        _tool(
            "get_next_free_ip",
            "The next free IP address(es) of one Nautobot prefix, like the workflow step 'Get "
            "Next Free IP'. Only reads: nothing is reserved, so the address can be given to "
            "someone else before it is used; say so in the answer. The search starts at the "
            "network address plus start_offset (default 1, so the network address itself is "
            "skipped). If the prefix exists in several namespaces the error lists them. Needs "
            "the addresses data switch.",
            NextFreeIpInput,
            free_ip.get_next_free_ip,
            gate=DataClass.ADDRESSES,
        ),
        _tool(
            "list_namespaces",
            "Nautobot IPAM namespaces (the same prefix can exist once per namespace).",
            NoInput,
            ipam.list_namespaces,
        ),
    )
