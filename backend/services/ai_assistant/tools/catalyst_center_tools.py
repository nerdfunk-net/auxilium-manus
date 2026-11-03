"""Cisco Catalyst Center reads for Ask the Net (doc/AI_TOOL_CHAIN.md §42).

Two pure reads, as the calling user: find a device in Catalyst Center, then read its facts (the
same ones as the workflow step ``get-catalyst-center-details``). Catalyst Center is a second
source next to Nautobot: the model looks at Nautobot first and uses the name, management address
or serial it finds there to look the device up here.

Data sharing (doc/ai_integration/AI_ASSISTANT.md §4), fail closed:

- Both tools need the inventory switch, checked before any request.
- Management addresses, serials, MACs, interface and VLAN addresses need the addresses switch;
  looking a device up *by* address or serial needs it too (otherwise existence would leak).
- Interface descriptions are free text and need the content switch.

A field no rule names is never sent. Upstream error text never reaches the model: a failed
source is a fixed sentence.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from services.ai_assistant.catalyst_center_reader import (
    CatalystAccessError,
    CatalystNotConfiguredError,
    CatalystSource,
    CatalystSourcesUnusableError,
)
from services.ai_assistant.data_sharing import DataClass, SharingPolicy, not_shared_marker
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.catalyst_center.common.exceptions import (
    CatalystCenterAuthError,
    CatalystCenterError,
    CatalystCenterNotFoundError,
    CatalystCenterRateLimitError,
    CatalystCenterTooManyDevicesError,
    CatalystCenterValidationError,
)
from services.catalyst_center.device_filters import CatalystCenterDeviceFilters

# Key of the reader in ``ToolContext.extras``; the surface builder puts it there.
CATALYST_READER_KEY = "catalyst_center_reader"
MAX_MATCHES = 10
DEFAULT_INTERFACE_PAGE = 25
MAX_INTERFACE_PAGE = 50
MAX_FIELD_CHARS = 500
# Server matches read per lookup key, and devices read by the case-insensitive scan (a controller
# matches hostnames case-sensitively, so a miss is repeated over the whole inventory).
SEARCH_CAP = 200
SCAN_CAP = 5000

Fact = Literal["device", "software", "interfaces", "vlans", "compliance"]
DEFAULT_FACTS: tuple[Fact, ...] = ("device", "software")

ALWAYS = "always"
Rule = DataClass | str

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

_NOT_CONFIGURED = ToolOutput(
    "No Cisco Catalyst Center source is configured. Tell the user that an "
    "administrator must add one under Settings -> Sources; do not guess Catalyst Center data.",
    is_error=True,
)
_UNUSABLE = ToolOutput(
    "Cisco Catalyst Center sources are configured but none is usable (credentials or settings "
    "fail). Tell the user to check the sources under Settings -> Sources; do not guess Catalyst "
    "Center data.",
    is_error=True,
)
_NO_ACCESS = ToolOutput(
    "You cannot read Catalyst Center data here (the user lacks the permission).", is_error=True
)
_BAD_LOOKUP = ToolOutput(
    "The lookup value is not valid (check the name, address or serial).", is_error=True
)


class CatalystReader(Protocol):
    async def sources(self) -> tuple[CatalystSource, ...]: ...


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindDeviceInput(_Input):
    name: Text | None = Field(
        None,
        description="Hostname as in Nautobot or Catalyst Center: the full name "
        "('LAB.local.zz') or the short one ('LAB'), any case.",
    )
    management_ip: Text | None = Field(
        None, description="Exact management IPv4 address, e.g. the primary IP Nautobot shows."
    )
    serial_number: Text | None = Field(None, description="Exact serial number.")

    @field_validator("management_ip")
    @classmethod
    def _valid_ip(cls, value: str | None) -> str | None:
        if value is not None:
            ipaddress.ip_address(value)  # ValueError becomes a validation message
        return value

    @model_validator(mode="after")
    def _one_key(self) -> FindDeviceInput:
        if not (self.name or self.management_ip or self.serial_number):
            raise ValueError("give name, management_ip or serial_number")
        return self


class DeviceDetailsInput(FindDeviceInput):
    facts: list[Fact] = Field(
        default_factory=lambda: list(DEFAULT_FACTS),
        min_length=1,
        description="Which facts to read: device (inventory record), software, interfaces, "
        "vlans (VLAN interfaces), compliance.",
    )
    interface_name_contains: Text | None = Field(
        None, description="Only interfaces whose name contains this text (facts: interfaces)."
    )
    interface_limit: Annotated[int, Field(ge=1, le=MAX_INTERFACE_PAGE)] = DEFAULT_INTERFACE_PAGE
    interface_offset: Annotated[int, Field(ge=0, le=100_000)] = 0


# -- what each result field needs ------------------------------------------------------------

_MATCH_RULES: Mapping[str, Rule] = {
    **dict.fromkeys(
        (
            "source_id",
            "id",
            "hostname",
            "role",
            "family",
            "device_type",
            "platform_id",
            "software_type",
            "software_version",
            "reachability_status",
            "collection_status",
        ),
        DataClass.INVENTORY,
    ),
    **dict.fromkeys(("management_ip", "serial_number", "mac_address"), DataClass.ADDRESSES),
}
_DEVICE_RULES: Mapping[str, Rule] = {
    **dict.fromkeys(
        (
            "id",
            "hostname",
            "platform_id",
            "family",
            "device_type",
            "role",
            "reachability_status",
            "reachability_failure_reason",
            "collection_status",
            "management_state",
            "support_level",
            "up_time",
            "boot_time",
            "last_updated",
            "location_name",
        ),
        DataClass.INVENTORY,
    ),
    **dict.fromkeys(("management_ip", "serial_number", "mac_address"), DataClass.ADDRESSES),
}
_SOFTWARE_RULES: Mapping[str, Rule] = {
    **dict.fromkeys(
        ("software_type", "software_version", "platform_id", "series"), DataClass.INVENTORY
    ),
    # The controller's free-text device description: content, like an interface description.
    "description": DataClass.CONTENT,
}
_INTERFACE_RULES: Mapping[str, Rule] = {
    **dict.fromkeys(
        (
            "name",
            "status",
            "admin_status",
            "interface_type",
            "port_mode",
            "port_type",
            "media_type",
            "speed",
            "duplex",
            "mtu",
            "vlan_id",
            "native_vlan_id",
            "voice_vlan",
        ),
        DataClass.INVENTORY,
    ),
    **dict.fromkeys(("mac_address", "ipv4_address", "ipv4_mask"), DataClass.ADDRESSES),
    # Free text someone typed (it can hold a password or an instruction).
    "description": DataClass.CONTENT,
}
_VLAN_RULES: Mapping[str, Rule] = {
    **dict.fromkeys(
        ("vlan_number", "vlan_type", "interface_name", "number_of_ips"), DataClass.INVENTORY
    ),
    **dict.fromkeys(("ip_address", "prefix", "network_address"), DataClass.ADDRESSES),
}
_COMPLIANCE_RULES: Mapping[str, Rule] = dict.fromkeys(
    ("status", "last_update_time", "items"), DataClass.INVENTORY
)
_COMPLIANCE_ITEM_RULES: Mapping[str, Rule] = dict.fromkeys(
    (
        "compliance_type",
        "status",
        "state",
        "last_sync_time",
        "remediation_supported",
        "ack_status",
    ),
    DataClass.INVENTORY,
)


def _project(
    policy: SharingPolicy,
    item: Mapping[str, Any],
    rules: Mapping[str, Rule],
    withheld: dict[str, str],
) -> dict[str, Any]:
    """Keep what the opt-ins allow and what has a value; record what a switch would release."""
    kept: dict[str, Any] = {}
    for key, value in item.items():
        rule = rules.get(key)
        if rule is None:
            continue  # fail closed: a field no rule names is never sent
        if isinstance(rule, DataClass) and not policy.allows(rule):
            if value not in (None, ""):
                withheld[key] = not_shared_marker(rule)["not_shared"]
            continue
        if value is not None:
            kept[key] = value
    return kept


def _dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump()


# -- errors ----------------------------------------------------------------------------------


def _failure_sentence(exc: Exception) -> str:
    """A short, fixed sentence for a failed call; never text from the response."""
    if isinstance(exc, CatalystCenterAuthError):
        return "Catalyst Center rejected the credentials of this source (check the source)."
    if isinstance(exc, CatalystCenterTooManyDevicesError):
        return "Too many devices match; look the device up by management IP or serial number."
    if isinstance(exc, CatalystCenterRateLimitError):
        return "Catalyst Center is rate limiting requests; try again later."
    if isinstance(exc, CatalystCenterNotFoundError):
        return "Catalyst Center does not know this resource."
    if isinstance(exc, CatalystCenterError):
        return "Catalyst Center did not answer as expected."
    return "Catalyst Center could not be reached."


_SOURCE_ERRORS = (CatalystCenterError, TimeoutError, OSError)


# -- lookup ----------------------------------------------------------------------------------


def _hostname_patterns(name: str) -> list[str]:
    """Spellings to send: a controller matches case-sensitively and full-string only.

    As typed, lower, upper and capitalised, for the name and the short label of a domain name,
    each also with ``.*`` for the name inside a domain. A first query that misses is repeated as
    a scan of the whole inventory (``_name_matches``), which is what makes "any case" true.
    """

    def spellings(text: str) -> set[str]:
        return {text, text.lower(), text.upper(), text.capitalize()}

    bases = spellings(name)
    if "." in name:
        bases |= spellings(name.split(".", 1)[0])
    # ``.*`` (the name inside a domain) only for the name itself when it already has a domain.
    domain_bases = bases if "." not in name else spellings(name)
    return sorted(bases | {f"{base}.*" for base in domain_bases})


def _hostname_ok(hostname: str | None, name: str) -> bool:
    """Same device: equal, the short name of a domain name, or the name inside the domain.

    ``LAB.*`` also matches ``LAB2.local.zz`` on the controller, so the result is checked here.
    """
    host, wanted = (hostname or "").lower(), name.lower()
    return (
        host == wanted
        or host.startswith(wanted + ".")
        or ("." in wanted and host == wanted.split(".", 1)[0])
    )


# The lookup keys, tried in this order: the first that finds a device is used. They are
# alternatives, not a conjunction (the controller ANDs filters, so a record from Nautobot with
# a stale IP would otherwise hide a device that its name finds).
_KEY_ORDER = ("serial_number", "management_ip", "name")


def _keys(args: FindDeviceInput) -> list[tuple[str, str]]:
    return [(key, value) for key in _KEY_ORDER if (value := getattr(args, key))]


def _filters(kind: str, value: str) -> CatalystCenterDeviceFilters:
    return CatalystCenterDeviceFilters.from_config(
        {
            "hostnames": _hostname_patterns(value) if kind == "name" else None,
            "management_ips": [value] if kind == "management_ip" else None,
            "serial_numbers": [value] if kind == "serial_number" else None,
        }
    )


class _Found:
    def __init__(self, sources: int = 0) -> None:
        self.matches: list[tuple[CatalystSource, Any]] = []
        self.errors: list[dict[str, str]] = []
        self.more = False
        self.sources = sources


async def _name_matches(source: CatalystSource, name: str) -> list[Any]:
    """Devices of one source named ``name``, in any case.

    The targeted query goes first; when it finds nothing (or matches too much to read), the whole
    inventory is read once and compared here.
    """
    try:
        devices = await source.devices.search_devices(
            _filters("name", name), max_devices=SEARCH_CAP
        )
        kept = [d for d in devices if _hostname_ok(d.hostname, name)]
    except CatalystCenterTooManyDevicesError:
        kept = []
    if kept:
        return kept
    everything = await source.devices.search_devices(
        CatalystCenterDeviceFilters(), max_devices=SCAN_CAP
    )
    return [d for d in everything if _hostname_ok(d.hostname, name)]


async def _search_key(sources: tuple[CatalystSource, ...], kind: str, value: str) -> _Found:
    found = _Found(len(sources))
    filters = None if kind == "name" else _filters(kind, value)

    async def one(source: CatalystSource) -> None:
        try:
            if filters is None:
                devices = await _name_matches(source, value)
            else:
                devices = list(await source.devices.search_devices(filters, max_devices=SEARCH_CAP))
        except _SOURCE_ERRORS as exc:
            found.errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            return
        found.matches.extend((source, device) for device in devices)

    await asyncio.gather(*(one(s) for s in sources))
    # Completion order of the sources must not decide which rows survive the cap.
    found.matches.sort(key=lambda m: (m[0].source_id, (m[1].hostname or "").lower(), m[1].id))
    found.more = len(found.matches) > MAX_MATCHES
    found.matches = found.matches[:MAX_MATCHES]
    return found


async def _search(sources: tuple[CatalystSource, ...], args: FindDeviceInput) -> _Found:
    """Try the lookup keys in order; the first one that finds a device decides."""
    found = _Found(len(sources))
    for kind, value in _keys(args):
        found = await _search_key(sources, kind, value)
        if found.matches:
            break
    return found


def _gate(ctx: ToolContext, args: FindDeviceInput) -> ToolOutput | None:
    """The switches a lookup needs, checked before any request."""
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    if (args.management_ip or args.serial_number) and not ctx.sharing.allows(DataClass.ADDRESSES):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.ADDRESSES), indent=1))
    return None


def _cap(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS] + "…" if len(value) > MAX_FIELD_CHARS else value
    if isinstance(value, dict):
        return {k: _cap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap(v) for v in value]
    return value


def _finish(ctx: ToolContext, payload: dict[str, Any]) -> ToolOutput:
    shaped = _cap(ctx.redactor.redact_data(payload))
    return ToolOutput(json.dumps(shaped, default=str, indent=1))


async def _sources_or_error(ctx: ToolContext) -> tuple[CatalystSource, ...] | ToolOutput:
    reader: CatalystReader = ctx.extras[CATALYST_READER_KEY]
    try:
        return await reader.sources()
    except CatalystNotConfiguredError:
        return _NOT_CONFIGURED
    except CatalystSourcesUnusableError:
        return _UNUSABLE
    except CatalystAccessError:
        return _NO_ACCESS


def _all_failed(found: _Found) -> ToolOutput | None:
    if found.matches or not found.errors or len(found.errors) < found.sources:
        return None
    detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in found.errors)
    return ToolOutput(f"Catalyst Center could not be searched. {detail}", is_error=True)


def _not_found(args: FindDeviceInput) -> str:
    key = args.name or args.management_ip or args.serial_number
    return (
        f"Device '{key}' not found in Catalyst Center. It may exist only in Nautobot or be named "
        "differently there: try its management IP or serial number from Nautobot."
    )


# -- find_catalyst_center_device -------------------------------------------------------------


def _match_record(source: CatalystSource, device: Any) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "id": device.id,
        "hostname": device.hostname,
        "role": device.role,
        "family": device.family,
        "device_type": device.device_type,
        "platform_id": device.platform_id,
        "software_type": device.software_type,
        "software_version": device.software_version,
        "reachability_status": device.reachability_status,
        "collection_status": device.collection_status,
        "management_ip": device.management_ip,
        "serial_number": device.serial_number,
        "mac_address": device.mac_address,
    }


async def _find(ctx: ToolContext, args: FindDeviceInput) -> ToolOutput:
    if (blocked := _gate(ctx, args)) is not None:
        return blocked
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    try:
        found = await _search(sources, args)
    except CatalystCenterValidationError:
        return _BAD_LOOKUP
    if (failed := _all_failed(found)) is not None:
        return failed
    withheld: dict[str, str] = {}
    matches = [
        _project(ctx.sharing, _match_record(source, device), _MATCH_RULES, withheld)
        for source, device in found.matches
    ]
    payload: dict[str, Any] = {"matches": matches}
    if not matches:
        payload["message"] = _not_found(args)
    if found.more:
        payload["has_more"] = True
    if found.errors:
        payload["source_errors"] = found.errors
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


# -- get_catalyst_center_device_details ------------------------------------------------------


def _interfaces_page(
    policy: SharingPolicy,
    items: tuple[Any, ...],
    args: DeviceDetailsInput,
    withheld: dict[str, str],
) -> dict[str, Any]:
    wanted = (args.interface_name_contains or "").lower()
    rows = [i for i in items if wanted in (i.name or "").lower()]
    page = rows[args.interface_offset : args.interface_offset + args.interface_limit]
    return {
        "total": len(rows),
        "offset": args.interface_offset,
        "has_more": args.interface_offset + len(page) < len(rows),
        "items": [_project(policy, _dump(i), _INTERFACE_RULES, withheld) for i in page],
    }


def _compliance(policy: SharingPolicy, value: Any, withheld: dict[str, str]) -> dict[str, Any]:
    data = _project(policy, {**_dump(value), "items": []}, _COMPLIANCE_RULES, withheld)
    data["items"] = [
        _project(policy, _dump(item), _COMPLIANCE_ITEM_RULES, withheld) for item in value.items
    ]
    return data


async def _read_facts(
    ctx: ToolContext, source: CatalystSource, device_id: str, args: DeviceDetailsInput
) -> tuple[dict[str, Any], dict[str, str]]:
    """One entry per requested fact; a failing fact is an error entry, the others still return."""
    policy, withheld = ctx.sharing, {}
    wanted = [f for f in dict.fromkeys(args.facts)]
    out: dict[str, Any] = {}

    async def entry(names: tuple[str, ...], fetch: Any, shape: Any) -> None:
        try:
            value = await fetch()
        except _SOURCE_ERRORS as exc:
            for name in names:
                out[name] = {"error": _failure_sentence(exc)}
            return
        shaped = shape(value)
        for name in names:
            keyed = isinstance(shaped, dict) and name in shaped
            out[name] = {"data": shaped[name] if keyed else shaped}

    jobs = []
    record = tuple(n for n in ("device", "software") if n in wanted)
    if record:
        jobs.append(
            entry(
                record,
                lambda: source.details.get_device_and_software(device_id),
                lambda v: {
                    "device": _project(policy, _dump(v[0]), _DEVICE_RULES, withheld),
                    "software": _project(policy, _dump(v[1]), _SOFTWARE_RULES, withheld),
                },
            )
        )
    if "interfaces" in wanted:
        jobs.append(
            entry(
                ("interfaces",),
                lambda: source.details.get_interfaces(device_id),
                lambda v: _interfaces_page(policy, v, args, withheld),
            )
        )
    if "vlans" in wanted:
        jobs.append(
            entry(
                ("vlans",),
                lambda: source.details.get_vlans(device_id),
                lambda v: [_project(policy, _dump(i), _VLAN_RULES, withheld) for i in v],
            )
        )
    if "compliance" in wanted:
        jobs.append(
            entry(
                ("compliance",),
                lambda: source.details.get_compliance(device_id),
                lambda v: _compliance(policy, v, withheld),
            )
        )
    await asyncio.gather(*jobs)
    return {name: out[name] for name in wanted}, withheld


def _ambiguous(found: _Found) -> ToolOutput:
    names = "; ".join(
        f"{d.hostname} (source '{s.source_id}', role {d.role or 'unknown'})"
        for s, d in found.matches
    )
    return ToolOutput(
        f"The lookup matches {len(found.matches)} devices in Catalyst Center: {names}. Ask the "
        "user which one, or look up by management IP or serial number.",
        is_error=True,
    )


async def _details(ctx: ToolContext, args: DeviceDetailsInput) -> ToolOutput:
    if (blocked := _gate(ctx, args)) is not None:
        return blocked
    sources = await _sources_or_error(ctx)
    if isinstance(sources, ToolOutput):
        return sources
    try:
        found = await _search(sources, args)
    except CatalystCenterValidationError:
        return _BAD_LOOKUP
    if (failed := _all_failed(found)) is not None:
        return failed
    if not found.matches:
        payload: dict[str, Any] = {"found": False, "message": _not_found(args)}
        if found.errors:
            payload["source_errors"] = found.errors
        return _finish(ctx, payload)
    if len(found.matches) > 1:
        return _ambiguous(found)
    source, device = found.matches[0]
    facts, withheld = await _read_facts(ctx, source, device.id, args)
    payload = {
        "found": True,
        "source_id": source.source_id,
        "device_id": device.id,
        "hostname": device.hostname,
        "facts": facts,
    }
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


def build_catalyst_center_tools() -> tuple[Tool, ...]:
    """The Catalyst Center read tools; the surface offers them only with a reader."""

    async def find(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _find(ctx, args)

    async def details(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _details(ctx, args)

    return (
        Tool(
            "find_catalyst_center_device",
            "Look a device up in Cisco Catalyst Center (the network controller) by hostname, "
            "management IP or serial number. Use it after Nautobot (get_device) for 'is it in "
            "Catalyst Center': pass the name, or the primary IP / serial Nautobot shows. A name "
            "matches the full or short hostname in any case. Give one key; several are "
            "alternatives tried in the order serial number, management IP, name, and the first "
            "that finds a device is used. An empty matches list is an answer "
            "(the device is not managed there), not an error. If it says no Catalyst Center "
            "source is configured, tell the user. Needs the inventory data switch; lookup by IP "
            "or serial and the addresses in the result also need the addresses switch.",
            FindDeviceInput,
            find,
        ),
        Tool(
            "get_catalyst_center_device_details",
            "Facts of one device from Cisco Catalyst Center, the same as the workflow step "
            "'Get Catalyst Center Details': device (serial, role, reachability, uptime), software "
            "(type and version), interfaces (status, speed, duplex, VLANs; paged with "
            "interface_limit / interface_offset, narrow with interface_name_contains), vlans "
            "(VLAN interfaces) and compliance. Defaults to device and software; ask for more "
            "facts only when needed. Look the device up by name, management IP or serial; "
            "several matches are an error that lists them. It is the controller's last "
            "collected view, not a live command. Needs the inventory data switch; addresses and "
            "serials need the addresses switch, interface descriptions the content switch.",
            DeviceDetailsInput,
            details,
        ),
    )
