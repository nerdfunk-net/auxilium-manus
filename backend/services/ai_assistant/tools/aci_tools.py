"""Cisco ACI device reads for Ask the Net (doc/plans/ACI_TOOL_CHAIN.md, phase 1).

Three pure reads, as the calling user: ``find_aci_device``, ``list_aci_devices`` and
``get_aci_device_details`` (the facts of the workflow step ``get-aci-details``).

Data sharing, fail closed: every tool needs the inventory switch, checked before any request;
looking a device up *by* address or serial needs the addresses switch too (otherwise existence
would leak). A result field no rule names is never sent. Upstream error text never reaches the
model: a failed source is a fixed sentence.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from fnmatch import fnmatchcase
from typing import Annotated, Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

import service_factory
from models.aci import AciDevice
from services.aci.common.exceptions import (
    AciAuthError,
    AciError,
    AciNotFoundError,
    AciRateLimitError,
    AciTooManyDevicesError,
)
from services.ai_assistant.aci_reader import (
    AciAccessError,
    AciNotConfiguredError,
    AciSource,
    AciSourcesUnusableError,
)
from services.ai_assistant.data_sharing import DataClass, SharingPolicy, not_shared_marker
from services.ai_assistant.tools.aci_fields import project
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.envelope import PREVIEW_ROWS
from services.auth.login_rate_limiter import RateLimitExceededError

ACI_READER_KEY = "aci_reader"
# A call can cost the APIC many reads (a cold policy snapshot is about 17), so it has a budget of
# its own per user, on top of the chat budget. Checked after the permission, before any request.
RATE_BUCKET = "ai-aci-read"
RATE_ATTEMPTS = 20
RATE_WINDOW_SECONDS = 60
# What a call costs in that budget: one slot per call is right for a cached or single read, but
# a leaf walk (include_deployed_on: up to 50 leaves, three class reads each), a full subnet read or
# a call that asks for many facts puts many requests on the APIC.
COST_FULL_SUBNET_READ = 2
COST_LEAF_WALK = 5
FACTS_PER_COST_UNIT = 4
MAX_MATCHES = 10
DEFAULT_PAGE = 25
MAX_PAGE = 50
MAX_FIELD_CHARS = 500
MAX_PARALLEL_FACTS = 4

Fact = Literal[
    "device",
    "software",
    "hardware",
    "interfaces",
    "neighbors",
    "vlans",
    "health",
    "faults",
    "routes",
    "protocols",
    "endpoints",
    "vpc",
    "epgs",
    "contracts",
]
DEFAULT_FACTS: tuple[Fact, ...] = ("device", "software")
# fact name -> AciDetailsService method taking (pod_id, node_id)
_FACT_METHODS: Mapping[str, str] = {
    "hardware": "get_hardware",
    "interfaces": "get_interfaces",
    "neighbors": "get_neighbors",
    "vlans": "get_vlans",
    "health": "get_health",
    "faults": "get_faults",
    "routes": "get_routes",
    "protocols": "get_protocols",
    "endpoints": "get_endpoints",
    "vpc": "get_vpc",
    "epgs": "get_epgs",
    "contracts": "get_contracts",
}

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

_NOT_CONFIGURED = ToolOutput(
    "No Cisco ACI source is configured. Tell the user that an administrator must add one under "
    "Settings -> Sources; do not guess ACI data.",
    is_error=True,
)
_UNUSABLE = ToolOutput(
    "Cisco ACI sources are configured but none is usable (credentials or settings fail). Tell "
    "the user to check the sources under Settings -> Sources; do not guess ACI data.",
    is_error=True,
)
_RATE_LIMITED = ToolOutput(
    "Too many ACI reads in a short time; ask the user to try again in a minute.", is_error=True
)
_NO_ACCESS = ToolOutput(
    "You cannot read ACI data here (the user lacks the permission).", is_error=True
)


class AciReader(Protocol):
    async def sources(self) -> tuple[AciSource, ...]: ...


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _SourceInput(_Input):
    source: Text | None = Field(
        None, description="Only this ACI source (its id). Without it every source is searched."
    )


class FindDeviceInput(_SourceInput):
    name: Text | None = Field(
        None, description="Switch name, any case; * and ? are wildcards ('leaf-1*')."
    )
    node_id: Annotated[int, Field(ge=1, le=100_000)] | None = Field(
        None, description="Fabric node id, e.g. 101."
    )
    serial_number: Text | None = Field(None, description="Exact serial number.")
    management_ip: Text | None = Field(None, description="Exact management IPv4 address.")

    @model_validator(mode="after")
    def _one_key(self) -> FindDeviceInput:
        if not (self.name or self.node_id or self.serial_number or self.management_ip):
            raise ValueError("give name, node_id, serial_number or management_ip")
        return self


class ListDevicesInput(_SourceInput):
    role: Literal["leaf", "spine"] | None = None
    pod_id: Annotated[int, Field(ge=1, le=1000)] | None = None
    name_contains: Text | None = None
    model: Text | None = Field(None, description="Exact model, e.g. N9K-C93180YC-FX.")
    limit: Annotated[int, Field(ge=1, le=PREVIEW_ROWS)] = PREVIEW_ROWS
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0


class DeviceDetailsInput(FindDeviceInput):
    facts: list[Fact] = Field(
        default_factory=lambda: list(DEFAULT_FACTS),
        min_length=1,
        max_length=len(Fact.__args__),  # type: ignore[attr-defined]
        description="Facts to read: device, software, hardware, interfaces, neighbors, vlans, "
        "health, faults, routes, protocols, endpoints, vpc, epgs, contracts.",
    )
    interface_name_contains: Text | None = Field(
        None, description="Only interfaces whose name contains this text (fact: interfaces)."
    )
    limit: Annotated[int, Field(ge=1, le=MAX_PAGE)] = DEFAULT_PAGE
    offset: Annotated[int, Field(ge=0, le=100_000)] = 0
    filter_offset: Annotated[int, Field(ge=0, le=100_000)] = Field(
        0,
        description="Fact contracts only: offset of the filter entries (the rules use offset), "
        "so the two lists page independently.",
    )

    @field_validator("facts")
    @classmethod
    def _unique(cls, value: list[Fact]) -> list[Fact]:
        return list(dict.fromkeys(value))


# -- errors ------------------------------------------------------------------------------------


def _failure_sentence(exc: Exception) -> str:
    """A short, fixed sentence for a failed call; never text from the response."""
    if isinstance(exc, AciAuthError):
        return "The APIC rejected the credentials of this source (check the source)."
    if isinstance(exc, AciTooManyDevicesError) or getattr(exc, "code", None) == "too_many_objects":
        return "Too many objects match; narrow the lookup (a tenant, profile or EPG)."
    if getattr(exc, "code", None) == "unsafe_endpoint_dn":
        return "The APIC returned an endpoint name this tool cannot query safely."
    if isinstance(exc, AciRateLimitError):
        return "The APIC is rate limiting requests; try again later."
    if isinstance(exc, AciNotFoundError):
        return "The APIC does not know this resource."
    if isinstance(exc, AciError):
        return "The APIC did not answer as expected."
    return "The APIC could not be reached."


_SOURCE_ERRORS = (AciError, TimeoutError, OSError)


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


async def _sources_or_error(
    ctx: ToolContext, only: str | None, cost: int = 1
) -> tuple[AciSource, ...] | ToolOutput:
    reader: AciReader = ctx.extras[ACI_READER_KEY]
    try:
        sources = await reader.sources()
    except AciNotConfiguredError:
        return _NOT_CONFIGURED
    except AciSourcesUnusableError:
        return _UNUSABLE
    except AciAccessError:
        return _NO_ACCESS
    if not await _within_budget(ctx.user_id, cost):
        return _RATE_LIMITED
    if only is not None:
        sources = tuple(s for s in sources if s.source_id == only)
        if not sources:
            return ToolOutput(f"No usable ACI source '{only}'.", is_error=True)
    return sources


async def _within_budget(user_id: int, cost: int = 1) -> bool:
    """Spend ``cost`` slots of the user's budget; False, with nothing spent, when it does not fit.

    The slots are reserved one by one and all refunded when one is refused, so a call that is too
    expensive for what is left does not eat the budget of cheaper calls.
    """
    limiter = service_factory.build_user_rate_limiter(
        RATE_BUCKET, RATE_ATTEMPTS, RATE_WINDOW_SECONDS
    )
    key = f"{RATE_BUCKET}:{user_id}"
    members: list[str] = []
    try:
        for _ in range(cost):
            members.append(await asyncio.to_thread(limiter.reserve, key))
    except RateLimitExceededError:
        for member in members:
            await asyncio.to_thread(limiter.release, key, member)
        return False
    return True


def _gate(ctx: ToolContext, args: _SourceInput) -> ToolOutput | None:
    """The switches a call needs, checked before any request."""
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.INVENTORY), indent=1))
    by_address = getattr(args, "serial_number", None) or getattr(args, "management_ip", None)
    if by_address and not ctx.sharing.allows(DataClass.ADDRESSES):
        return ToolOutput(json.dumps(not_shared_marker(DataClass.ADDRESSES), indent=1))
    return None


# -- lookup ------------------------------------------------------------------------------------

# Alternatives, tried in this order: the first key that finds a device decides.
_KEY_ORDER = ("node_id", "serial_number", "management_ip", "name")


def _match(device: AciDevice, kind: str, value: Any) -> bool:
    if kind == "node_id":
        return device.node_id == value
    if kind == "serial_number":
        return (device.serial_number or "").lower() == str(value).lower()
    if kind == "management_ip":
        return value in (device.management_ip, device.oob_ip, device.inb_ip)
    return fnmatchcase(device.name.lower(), str(value).lower())


class _Found:
    def __init__(self, sources: int) -> None:
        self.matches: list[tuple[AciSource, AciDevice]] = []
        self.errors: list[dict[str, str]] = []
        self.more = False
        self.sources = sources


async def _read_all(sources: tuple[AciSource, ...]) -> _Found:
    """Every leaf and spine of every source; a fabric is small and the filters run here."""
    found = _Found(len(sources))

    async def one(source: AciSource) -> None:
        try:
            devices = await source.devices.search()
        except _SOURCE_ERRORS as exc:
            found.errors.append({"source_id": source.source_id, "error": _failure_sentence(exc)})
            return
        found.matches.extend((source, device) for device in devices)

    await asyncio.gather(*(one(s) for s in sources))
    found.matches.sort(key=lambda m: (m[0].source_id, m[1].node_id))
    return found


def _narrow(found: _Found, args: FindDeviceInput) -> _Found:
    for kind in _KEY_ORDER:
        value = getattr(args, kind)
        if value is None:
            continue
        hits = [(s, d) for s, d in found.matches if _match(d, kind, value)]
        if hits:
            out = _Found(found.sources)
            out.errors = found.errors
            out.more = len(hits) > MAX_MATCHES
            out.matches = hits[:MAX_MATCHES]
            return out
    out = _Found(found.sources)
    out.errors = found.errors
    return out


def _all_failed(found: _Found) -> ToolOutput | None:
    if found.matches or not found.errors or len(found.errors) < found.sources:
        return None
    detail = "; ".join(f"source '{e['source_id']}': {e['error']}" for e in found.errors)
    return ToolOutput(f"The ACI fabric could not be read. {detail}", is_error=True)


def _not_found(args: FindDeviceInput) -> str:
    key = args.name or args.node_id or args.serial_number or args.management_ip
    return (
        f"No leaf or spine '{key}' in the ACI fabric. It may exist only in Nautobot, or be "
        "named differently there: try its serial number or node id."
    )


def _device_record(
    policy: SharingPolicy, source: AciSource, device: AciDevice, withheld: dict[str, str]
) -> dict[str, Any]:
    return {"source_id": source.source_id, **project(policy, device, withheld)}


async def _find(ctx: ToolContext, args: FindDeviceInput) -> ToolOutput:
    if (blocked := _gate(ctx, args)) is not None:
        return blocked
    sources = await _sources_or_error(ctx, args.source)
    if isinstance(sources, ToolOutput):
        return sources
    found = await _read_all(sources)
    if (failed := _all_failed(found)) is not None:
        return failed
    found = _narrow(found, args)
    withheld: dict[str, str] = {}
    matches = [_device_record(ctx.sharing, s, d, withheld) for s, d in found.matches]
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


async def _list(ctx: ToolContext, args: ListDevicesInput) -> ToolOutput:
    if (blocked := _gate(ctx, args)) is not None:
        return blocked
    sources = await _sources_or_error(ctx, args.source)
    if isinstance(sources, ToolOutput):
        return sources
    found = await _read_all(sources)
    if (failed := _all_failed(found)) is not None:
        return failed
    wanted = (args.name_contains or "").lower()
    rows = [
        (s, d)
        for s, d in found.matches
        if (args.role is None or d.role == args.role)
        and (args.pod_id is None or d.pod_id == args.pod_id)
        and (args.model is None or d.model == args.model)
        and wanted in d.name.lower()
    ]
    page = rows[args.offset : args.offset + args.limit]
    withheld: dict[str, str] = {}
    payload: dict[str, Any] = {
        "total": len(rows),
        "offset": args.offset,
        "has_more": args.offset + len(page) < len(rows),
        "devices": [_device_record(ctx.sharing, s, d, withheld) for s, d in page],
    }
    if found.errors:
        payload["source_errors"] = found.errors
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


# -- get_aci_device_details --------------------------------------------------------------------


def _page(items: Any, args: DeviceDetailsInput, fact: str, offset: int | None = None) -> Any:
    """Cut a list fact to one page; ``interfaces`` can be narrowed by name first."""
    start = args.offset if offset is None else offset
    if not isinstance(items, (list, tuple)):
        return items
    rows = list(items)
    if fact == "interfaces" and args.interface_name_contains:
        wanted = args.interface_name_contains.lower()
        rows = [r for r in rows if wanted in (getattr(r, "name", "") or "").lower()]
    window = rows[start : start + args.limit]
    return {
        "total": len(rows),
        "offset": start,
        "has_more": start + len(window) < len(rows),
        "items": window,
    }


def _bounded(value: Any, args: DeviceDetailsInput, fact: str) -> Any:
    """Page a list fact; the contracts fact pages its rules and filters."""
    if fact == "contracts":
        return {
            "rules": _page(value.rules, args, fact),
            "filters": _page(value.filters, args, fact, args.filter_offset),
        }
    return _page(value, args, fact)


def _shape(policy: SharingPolicy, value: Any, withheld: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _shape(policy, v, withheld) for k, v in value.items()}
    return project(policy, value, withheld)


async def _read_facts(
    ctx: ToolContext, source: AciSource, device: AciDevice, args: DeviceDetailsInput
) -> tuple[dict[str, Any], dict[str, str]]:
    """One entry per requested fact; a failing fact is an error entry, the others still return."""
    # ``_details`` refuses a switch without a pod id before it gets here.
    pod, node = device.pod_id or 0, device.node_id
    withheld: dict[str, str] = {}
    out: dict[str, Any] = {}
    gate = asyncio.Semaphore(MAX_PARALLEL_FACTS)

    async def guarded(names: tuple[str, ...], fetch: Any, pick: Any) -> None:
        async with gate:
            try:
                value = await fetch()
            except _SOURCE_ERRORS as exc:
                for name in names:
                    out[name] = {"error": _failure_sentence(exc)}
                return
        for name in names:
            out[name] = {"data": _shape(ctx.sharing, pick(value, name), withheld)}

    jobs = []
    record = tuple(n for n in ("device", "software") if n in args.facts)
    if record:
        jobs.append(
            guarded(
                record,
                lambda: source.details.get_device_and_software(pod, node),
                lambda v, n: v[0] if n == "device" else v[1],
            )
        )
    for name in args.facts:
        if name in _FACT_METHODS:
            method = getattr(source.details, _FACT_METHODS[name])
            jobs.append(
                guarded((name,), lambda m=method: m(pod, node), lambda v, n: _bounded(v, args, n))
            )
    await asyncio.gather(*jobs)
    return {name: out[name] for name in args.facts}, withheld


def redacted_error(ctx: ToolContext, message: str) -> ToolOutput:
    """An error sentence that names things from the fabric: redacted like a success payload."""
    return ToolOutput(ctx.redactor.redact(message), is_error=True)


def _ambiguous(ctx: ToolContext, found: _Found) -> ToolOutput:
    names = "; ".join(
        f"{d.name} (node {d.node_id}, source '{s.source_id}')" for s, d in found.matches
    )
    return redacted_error(
        ctx,
        f"The lookup matches {len(found.matches)} switches in ACI: {names}. Ask the user "
        "which one, or look up by node id or serial number.",
    )


async def _details(ctx: ToolContext, args: DeviceDetailsInput) -> ToolOutput:
    if (blocked := _gate(ctx, args)) is not None:
        return blocked
    # Many facts are many APIC reads: one more budget slot for every four beyond the first.
    cost = 1 + (len(args.facts) - 1) // FACTS_PER_COST_UNIT
    sources = await _sources_or_error(ctx, args.source, cost)
    if isinstance(sources, ToolOutput):
        return sources
    found = await _read_all(sources)
    if (failed := _all_failed(found)) is not None:
        return failed
    found = _narrow(found, args)
    if not found.matches:
        payload: dict[str, Any] = {"found": False, "message": _not_found(args)}
        if found.errors:
            payload["source_errors"] = found.errors
        return _finish(ctx, payload)
    if len(found.matches) > 1:
        return _ambiguous(ctx, found)
    source, device = found.matches[0]
    if device.pod_id is None:
        return redacted_error(
            ctx,
            f"The pod id of switch {device.name} (node {device.node_id}) is unknown, so its "
            "facts cannot be read. Do not guess a pod.",
        )
    facts, withheld = await _read_facts(ctx, source, device, args)
    payload = {
        "found": True,
        "source_id": source.source_id,
        "node_id": device.node_id,
        "name": device.name,
        "facts": facts,
    }
    if withheld:
        payload["withheld_fields"] = withheld
    return _finish(ctx, payload)


def build_aci_tools() -> tuple[Tool, ...]:
    """The ACI read tools; the surface offers them only with a reader."""

    async def find(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _find(ctx, args)

    async def list_(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list(ctx, args)

    async def details(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _details(ctx, args)

    from services.ai_assistant.tools.aci_flow_tools import build_aci_flow_tools
    from services.ai_assistant.tools.aci_lookup_tools import build_aci_lookup_tools
    from services.ai_assistant.tools.aci_policy_tools import build_aci_policy_tools

    return (
        *build_aci_lookup_tools(),
        *build_aci_policy_tools(),
        *build_aci_flow_tools(),
        Tool(
            "find_aci_device",
            "Look a leaf or spine up in the Cisco ACI fabric (APIC) by name (wildcards * ?), node "
            "id, serial number or management IP. Use it after Nautobot for 'is it in ACI'. Give "
            "one key; several are alternatives tried in the order node id, serial, management IP, "
            "name. An empty matches list is an answer (not in the fabric), not an error. If it "
            "says no ACI source is configured, tell the user. Needs the inventory switch; lookup "
            "by serial or IP and those fields need the addresses switch.",
            FindDeviceInput,
            find,
        ),
        Tool(
            "list_aci_devices",
            "List the leaf and spine switches of the Cisco ACI fabric: node id, name, role, pod, "
            "model, software, state. Filter by role, pod_id, model or name_contains; page with "
            "limit / offset (total says how many match). Answers 'which leafs do we have'. Needs "
            "the inventory switch; serials and addresses need the addresses switch.",
            ListDevicesInput,
            list_,
        ),
        Tool(
            "get_aci_device_details",
            "Facts of one ACI leaf or spine, the same as the workflow step 'Get Details from "
            "ACI': device, software (default), hardware, interfaces, neighbors (LLDP/CDP), vlans, "
            "health, faults, routes, protocols (BGP, IS-IS, OSPF), endpoints, vpc, epgs (deployed "
            "on that leaf) and contracts (the rules the leaf enforces, not the contract objects). "
            "Ask only for the facts you need; list facts page with limit / offset, interfaces "
            "narrow with interface_name_contains. Look the switch up like find_aci_device; "
            "several matches are an error that lists them. It is the APIC's current view. Needs "
            "the inventory switch; addresses need the addresses switch, descriptions the content "
            "switch.",
            DeviceDetailsInput,
            details,
        ),
    )
