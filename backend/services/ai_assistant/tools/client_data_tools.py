"""``find_client`` / ``list_clients`` / ``get_client_history`` / ``get_client_data_coverage``:
where MAC and IP addresses were seen, from the data the ``collect-client-data`` workflow step
stored (doc/CLIENT_DATA.md, doc/AI_TOOL_CHAIN.md section 48).

Pure reads of stored observations, not a live lookup: every row says when it was collected. The
rows are class B data (device names and addresses), so the address tools need the inventory and
the addresses switches, checked before any read (otherwise existence would leak). Coverage lists
device names only and needs the inventory switch. The reader checks ``client_data:read`` per call.
"""

from __future__ import annotations

import ipaddress
import json
import re
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from services.ai_assistant.client_data_reader import ClientDataAccessError, ClientDataReader
from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.envelope import PREVIEW_ROWS, ResultEnvelope, envelope_output

# Key of the ``ClientDataReader`` in ``ToolContext.extras``; the surface builder puts it there.
CLIENT_DATA_READER_KEY = "client_data_reader"

_FETCH_ROWS = 50  # read this many observations, order them, then show the preview
_MAC_DIGITS = re.compile(r"^[0-9a-f]{12}$")
_MAC_SEPARATORS = re.compile(r"[.:\-]")
_HOSTNAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]{0,253}[A-Za-z0-9])?$")
_DIGITS_AND_DOTS = re.compile(r"^[0-9.]+$")

_HEX_ONLY = re.compile(r"^[0-9a-fA-F]{12}$")
_IP_PREFIX = r"^[0-9A-Fa-f:.]{1,45}$"

_NO_PERMISSION = ToolOutput(
    "You are not allowed to read client data (client_data:read is required). Tell the user.",
    is_error=True,
)
_COLLECTED_NOTE = (
    "This is not the live network: each row was collected by the Collect Client Data workflow "
    "step. age_seconds is the age of the port (or ARP entry); ip_age_seconds is the age of the "
    "ARP data the ip_address came from, which can be older or newer because ARP and the MAC "
    "table are collected separately. Quote both when they differ."
)
_UPLINK_NOTE = (
    "An observation with is_uplink=true is a port with other devices behind it: the host is "
    "behind it, not on it. uplink_reason says how that was decided: 'neighbor' is a switch, "
    "router or access point seen through LLDP or CDP on that port (uplink_to names it, also "
    "through a port-channel), 'mac_count' is only a port that learned many MACs (a guess: a "
    "busy hypervisor can look like this). likely_location marks the access port with the "
    "fewest MACs."
)
_NOT_SEEN_NOTE = (
    "Not seen by any collected device. It may be silent, aged out of the ARP and MAC tables, or "
    "behind a device that is not collected: check get_client_data_coverage before saying it is "
    "absent."
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class FindClientInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: Text = Field(
        description="A MAC address in any notation (aabb.ccdd.eeff, aa:bb:cc:dd:ee:ff), an IPv4 or "
        "IPv6 address, or a hostname, matched as a whole value."
    )


class ListClientsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: Text | None = Field(None, description="Only what this device saw (substring).")
    port: Text | None = Field(None, description="Only this port or interface (substring).")
    vlan: Text | None = Field(None, description="Only this VLAN id (substring).")
    vrf: Text | None = Field(None, description="Only this VRF (substring).")
    mac_contains: Text | None = Field(None, description="MAC address part, any notation.")
    ip_prefix: (
        Annotated[str, StringConstraints(strip_whitespace=True, pattern=_IP_PREFIX)] | None
    ) = Field(
        None,
        description="The start of the IP address, for example '10.1.' (all of 10.1.x.x, not "
        "110.1.x.x). Octet-aligned prefixes only; a CIDR such as 10.1.0.0/16 is not accepted.",
    )
    ip_contains: Text | None = Field(
        None,
        description="Text inside the IP address (a plain substring: '10.1.' also matches "
        "'110.1.2.3'). Use ip_prefix for a network.",
    )
    hostname_contains: Text | None = Field(None, description="Hostname part.")
    hide_uplinks: bool = Field(
        True, description="Leave out MAC-table rows on uplink ports (the default)."
    )
    page: int = Field(1, ge=1, le=10_000, description=f"Page of {PREVIEW_ROWS} rows.")


class GetClientHistoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mac_address: Text | None = Field(None, description="A MAC address in any notation.")
    ip_address: Text | None = Field(None, description="An IPv4 or IPv6 address.")
    hostname: Text | None = Field(None, description="A hostname.")

    @model_validator(mode="after")
    def _exactly_one(self) -> GetClientHistoryInput:
        given = [v for v in (self.mac_address, self.ip_address, self.hostname) if v]
        if len(given) != 1:
            raise ValueError("give exactly one of mac_address, ip_address or hostname")
        return self


class CoverageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(0, ge=0, le=100_000, description="Skip this many devices (to continue).")


def _reader(ctx: ToolContext) -> ClientDataReader:
    return ctx.extras[CLIENT_DATA_READER_KEY]


def _gate(ctx: ToolContext, *, addresses: bool = True) -> ToolOutput | None:
    classes = (DataClass.INVENTORY, DataClass.ADDRESSES) if addresses else (DataClass.INVENTORY,)
    for data_class in classes:
        if not ctx.sharing.allows(data_class):
            return ToolOutput(json.dumps(not_shared_marker(data_class)))
    return None


def _age_seconds(collected_at: str | None) -> int | None:
    if not collected_at:
        return None
    stamp = datetime.fromisoformat(collected_at)
    if stamp.tzinfo is None:  # a database without time zones (the unit tests' SQLite)
        stamp = stamp.replace(tzinfo=UTC)
    return max(int((datetime.now(UTC) - stamp).total_seconds()), 0)


def _observation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "device": row["device_name"],
        "port": row["port"],
        "vlan": row["vlan"],
        "vrf": row["vrf"],
        "ip_address": row["ip_address"],
        "hostname": row["hostname"],
        "mac_address": row["mac_address"],
        "macs_on_port": row["macs_on_port"],
        "is_uplink": row["is_uplink"],
        "uplink_reason": row.get("uplink_reason"),
        "uplink_to": row.get("uplink_to"),
        "likely_location": row["likely_location"],
        "collected_at": row["collected_at"],
        "age_seconds": _age_seconds(row["collected_at"]),
        "ip_collected_at": row.get("ip_collected_at"),
        "ip_age_seconds": _age_seconds(row.get("ip_collected_at")),
    }


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _classify(value: str) -> list[tuple[str, str]]:
    """The ways to read *value*, most likely first: a MAC, an IP address or a hostname.

    Twelve hex digits without a separator are a MAC in some tools and a valid hostname, so both
    are tried. Empty when it is none of them.
    """
    separated = ":" in value or "-" in value or "." in value
    if _MAC_DIGITS.match(_MAC_SEPARATORS.sub("", value).lower()) and (
        separated or _HEX_ONLY.match(value)
    ):
        candidates = [("mac_address", value)]
        if _HEX_ONLY.match(value) and _HOSTNAME.match(value):
            candidates.append(("hostname", value))
        return candidates
    if _is_ip(value):
        return [("ip_address", value)]
    if _DIGITS_AND_DOTS.match(value) or not _HOSTNAME.match(value):
        return []
    return [("hostname", value)]


def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (not row["likely_location"], row["is_uplink"], row["device_name"], row["port"] or "")


async def _find_client(ctx: ToolContext, args: FindClientInput) -> ToolOutput:
    if (gate := _gate(ctx)) is not None:
        return gate
    candidates = _classify(args.address)
    if not candidates:
        return ToolOutput(
            "Give a MAC address, an IPv4 or IPv6 address, or a hostname.", is_error=True
        )
    key, value, rows, total = candidates[0][0], candidates[0][1], [], 0
    for key, value in candidates:
        try:
            # The likely location is ordered before the page is cut: with many switches seeing
            # the host on their uplinks it would otherwise fall outside the rows fetched.
            rows, total = await _reader(ctx).observations(
                **{key: value}, exact=True, likely_first=True, page=1, page_size=_FETCH_ROWS
            )
        except ClientDataAccessError:
            return _NO_PERMISSION
        if rows:
            break
    ordered = sorted(rows, key=_sort_key)
    shown = [_observation(row) for row in ordered[:PREVIEW_ROWS]]
    likely = next((o for o in shown if o["likely_location"]), None)
    notes = [_COLLECTED_NOTE]
    if not rows:
        notes.append(_NOT_SEEN_NOTE)
    else:
        notes.append(_UPLINK_NOTE)
        if likely is None:
            notes.append("There is no access port among the observations (only uplinks or ARP).")
    envelope = ResultEnvelope(
        rows=shown, total_rows=total, truncated=total > len(shown), note=" ".join(notes)
    )
    return envelope_output(
        envelope,
        extra={
            "query": {
                "kind": key.removesuffix("_address") if key != "hostname" else key,
                "value": value,
            },
            "likely_location": (
                {k: likely[k] for k in ("device", "port", "vlan", "vrf", "ip_address", "hostname")}
                if likely
                else None
            ),
        },
    )


async def _list_clients(ctx: ToolContext, args: ListClientsInput) -> ToolOutput:
    if (gate := _gate(ctx)) is not None:
        return gate
    try:
        rows, total = await _reader(ctx).observations(
            device_name=args.device,
            port=args.port,
            vlan=args.vlan,
            vrf=args.vrf,
            mac_address=args.mac_contains,
            ip_address=args.ip_contains,
            ip_prefix=args.ip_prefix,
            hostname=args.hostname_contains,
            hide_uplinks=args.hide_uplinks,
            exact=False,
            page=args.page,
            page_size=PREVIEW_ROWS,
        )
    except ClientDataAccessError:
        return _NO_PERMISSION
    notes = [_COLLECTED_NOTE]
    if args.hide_uplinks:
        notes.append("Rows on uplink ports are left out (hide_uplinks).")
    if total > args.page * PREVIEW_ROWS:
        notes.append(f"Continue with page={args.page + 1}.")
    envelope = ResultEnvelope(
        rows=[_observation(row) for row in rows],
        total_rows=total,
        truncated=total > args.page * PREVIEW_ROWS,
        note=" ".join(notes),
    )
    return envelope_output(envelope, extra={"page": args.page})


async def _get_history(ctx: ToolContext, args: GetClientHistoryInput) -> ToolOutput:
    if (gate := _gate(ctx)) is not None:
        return gate
    try:
        history = await _reader(ctx).history(
            mac_address=args.mac_address,
            ip_address=args.ip_address,
            hostname=args.hostname,
            limit=PREVIEW_ROWS + 1,  # one more than shown: tells whether the list was cut
        )
    except ClientDataAccessError:
        return _NO_PERMISSION
    rows: list[dict[str, Any]] = []
    for kind in ("mac", "ip", "hostname"):
        for entry in history[f"{kind}_history"]:
            rows.append(
                {
                    "kind": kind,
                    "device": entry["device_name"],
                    "mac_address": entry.get("mac_address"),
                    "ip_address": entry.get("ip_address"),
                    "hostname": entry.get("hostname"),
                    "port": entry.get("port"),
                    "vlan": entry.get("vlan"),
                    "vrf": entry.get("vrf"),
                    "collected_at": entry["collected_at"],
                    "age_seconds": _age_seconds(entry["collected_at"]),
                }
            )
    envelope = ResultEnvelope(
        rows=rows[:PREVIEW_ROWS],
        total_rows=len(rows),
        truncated=len(rows) > PREVIEW_ROWS,
        # Cut at the source's limit: there may be more than were fetched.
        total_rows_exact=len(rows) <= PREVIEW_ROWS,
        note=(
            "Only the retained collections are searched: each device keeps its last few runs, so "
            "this is a short history, not a long timeline. Newest first. " + _COLLECTED_NOTE
        ),
    )
    return envelope_output(envelope)


async def _coverage(ctx: ToolContext, args: CoverageInput) -> ToolOutput:
    if (gate := _gate(ctx, addresses=False)) is not None:
        return gate
    try:
        collections = await _reader(ctx).coverage()
    except ClientDataAccessError:
        return _NO_PERMISSION
    summary = {
        "devices": len(collections),
        "arp_not_collected": sum(c["arp_status"] == "skipped" for c in collections),
        "mac_not_supported": sum(c["mac_status"] == "not_supported" for c in collections),
        "mac_not_collected": sum(c["mac_status"] == "skipped" for c in collections),
        "neighbours_not_collected": sum(
            c.get("neighbor_status", "skipped") == "skipped" for c in collections
        ),
    }
    if not collections:
        note = (
            "No client data has been collected yet. The Collect Client Data workflow step fills "
            "it; tell the user to run it."
        )
    else:
        note = (
            "These are the devices that were collected, and when. A status of not_supported means "
            "the device refused that command (a router has no MAC address table): its table is "
            "missing, not empty. ARP and the MAC table are collected separately and can come from "
            "different runs: use arp_age_seconds and mac_age_seconds, and a table with status "
            "skipped was never collected. The LLDP/CDP neighbours (neighbor_status, "
            "neighbor_entries, neighbor_age_seconds) are a third table: where they were never "
            "collected, uplinks are only guessed from the number of MACs. vrf_results lists each "
            "VRF of the device with the status of its ARP table: ok with 0 rows is a VRF with no "
            "entries, not_supported or no_template means the table could not be read, null means "
            "VRFs were not discovered. "
            "A device that is not listed was never collected, so "
            "addresses behind it are unknown. " + _COLLECTED_NOTE
        )
    devices = [
        {
            "device": c["device_name"],
            "collected_at": c["collected_at"],
            "age_seconds": _age_seconds(c["collected_at"]),
            "arp_collected_at": c["arp_collected_at"],
            "arp_age_seconds": _age_seconds(c["arp_collected_at"]),
            "mac_collected_at": c["mac_collected_at"],
            "mac_age_seconds": _age_seconds(c["mac_collected_at"]),
            "arp_status": c["arp_status"],
            "mac_status": c["mac_status"],
            "neighbor_status": c.get("neighbor_status", "skipped"),
            "neighbor_age_seconds": _age_seconds(c.get("neighbor_collected_at")),
            "neighbor_entries": c.get("neighbor_rows", 0),
            "vrf_status": c["vrf_status"],
            "arp_entries": c["arp_rows"],
            "mac_entries": c["mac_rows"],
            "vrfs": c["vrf_count"],
            "vrf_results": c.get("vrfs"),
        }
        for c in collections
    ]
    # An envelope drops whole rows to fit the output limit and says where to continue; a plain
    # JSON dump would be cut mid-array past a few dozen devices.
    envelope = ResultEnvelope(
        rows=devices[args.offset :],
        total_rows=len(devices),
        truncated=False,
        note=note,
    )
    return envelope_output(envelope, extra={"offset": args.offset, "summary": summary})


def build_client_data_tools() -> tuple[Tool, ...]:
    """The client data read tools; the surface offers them only with a reader."""

    async def find(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _find_client(ctx, args)

    async def list_(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _list_clients(ctx, args)

    async def history(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _get_history(ctx, args)

    async def coverage(ctx: ToolContext, args: Any) -> ToolOutput:
        return await _coverage(ctx, args)

    return (
        Tool(
            "find_client",
            "Where is a MAC address, IP address or hostname connected? Reads the client data the "
            "Collect Client Data workflow step stored from the switches' and routers' MAC address "
            "and ARP tables (not the live network: every row has collected_at). Give one value; "
            "it is matched as a whole. Returns every device that saw it, the likely_location "
            "first (the access port with the fewest MACs) and the uplink observations behind "
            "which the host sits. An empty result means no collected device saw it, never that "
            "it does not exist: call get_client_data_coverage before saying it is absent. Needs "
            "the inventory and addresses switches.",
            FindClientInput,
            find,
        ),
        Tool(
            "list_clients",
            "List collected client observations (MAC, IP, hostname, device, port, VLAN, VRF), "
            "filtered by device, port, VLAN, VRF, the start of the IP address (ip_prefix) or "
            "parts of the MAC, IP or hostname (plain text matches). Use it for 'what is on "
            "VLAN 100 of switch X' or 'which hosts are in 10.1.x.x' (ip_prefix='10.1.'). "
            "Uplink ports are left out unless hide_uplinks is false. 20 rows per page with "
            "the total. Needs the inventory and addresses switches.",
            ListClientsInput,
            list_,
        ),
        Tool(
            "get_client_history",
            "Earlier observations of one MAC address, IP address or hostname across the retained "
            "collections (a device keeps only its last few runs, so this is short). Use it for "
            "'was this host seen on another port before'. Give exactly one value. Needs the "
            "inventory and addresses switches.",
            GetClientHistoryInput,
            history,
        ),
        Tool(
            "get_client_data_coverage",
            "Which devices the client data covers, when each was collected and whether each "
            "command worked (ok, not_supported, no_template, skipped). Use it to judge how far an "
            "empty find_client answer can be trusted and how old the data is. Rows are devices; "
            "continue with offset. Needs the inventory switch.",
            CoverageInput,
            coverage,
        ),
    )
