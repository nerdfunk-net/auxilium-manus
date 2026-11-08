"""Pure parsing helpers for the collect-client-data step (no I/O).

Netmiko returns a command's TextFSM result as a JSON string when a template matched and
as the raw device text otherwise. The raw text is also returned when a template exists
but the table is empty, so ``classify_output`` asks ntc-templates whether a template
exists to tell "empty table" from "no template".
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from typing import Any

from ntc_templates.parse import ParsingException, parse_output

from models.client_data import CollectionStatus
from services.network.netmiko.output_check import find_cli_error
from workflow_steps.collect_client_data.commands import (
    CMD_ARP,
    CMD_CDP,
    CMD_CHANNELS_IOS,
    CMD_CHANNELS_NXOS,
    CMD_LLDP,
    CMD_MAC_TABLE,
    CMD_VRF_LIST,
    NEIGHBOR_COMMANDS,
)

STATUS_OK: CollectionStatus = "ok"
STATUS_NOT_SUPPORTED: CollectionStatus = "not_supported"
STATUS_NO_TEMPLATE: CollectionStatus = "no_template"
STATUS_SKIPPED: CollectionStatus = "skipped"

_MAC_SEPARATORS = re.compile(r"[.:\-]")
_HEX_12 = re.compile(r"^[0-9a-f]{12}$")
_SVI = re.compile(r"^(?:vlan|vl)(\d{1,4})$", re.IGNORECASE)
_DEFAULT_VRF = "default"
_MAX_VRF_INDENT = 4
# VRF names are put into "show ip arp vrf <name>": allow plain names only (and the column is 64).
_SAFE_VRF_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}$")


@dataclass(frozen=True)
class ArpEntry:
    ip_address: str
    mac_address: str | None
    interface: str | None
    vrf: str | None
    vlan: str | None


@dataclass(frozen=True)
class MacEntry:
    mac_address: str
    vlan: str | None
    port: str | None


# Capabilities a neighbour can advertise, as a closed vocabulary. A port with a neighbour that
# bridges, routes or is a wireless access point has other devices behind it: it is an uplink.
INFRASTRUCTURE_CAPABILITIES = frozenset({"bridge", "router", "wlan_ap"})


@dataclass(frozen=True)
class NeighborEntry:
    """A device seen on a local port through LLDP or CDP."""

    port: str
    neighbor_name: str | None
    neighbor_port: str | None
    protocol: str
    capabilities: tuple[str, ...]

    @property
    def is_infrastructure(self) -> bool:
        return bool(INFRASTRUCTURE_CAPABILITIES.intersection(self.capabilities))


@dataclass(frozen=True)
class OutputClass:
    status: CollectionStatus
    rows: list[dict[str, Any]] = field(default_factory=list)


def normalise_mac(raw: str | None) -> str | None:
    """Return ``aabb.ccdd.eeff`` for any common MAC notation, or ``None`` if not a MAC."""
    if not raw:
        return None
    digits = _MAC_SEPARATORS.sub("", raw.strip()).lower()
    if not _HEX_12.match(digits):
        return None
    return f"{digits[0:4]}.{digits[4:8]}.{digits[8:12]}"


# Long interface names -> the short form the MAC address table prints. "Ethernet" is "Eth" on
# NX-OS and "Et" on IOS; names that are already short are left as they are.
_PORT_PREFIXES = {
    "gigabitethernet": "Gi",
    "tengigabitethernet": "Te",
    "twentyfivegige": "Twe",
    "fortygigabitethernet": "Fo",
    "hundredgige": "Hu",
    "fastethernet": "Fa",
    "port-channel": "Po",
    "gi": "Gi",
    "te": "Te",
    "twe": "Twe",
    "fo": "Fo",
    "hu": "Hu",
    "fa": "Fa",
    "po": "Po",
}
_PORT_NAME = re.compile(r"^([A-Za-z][A-Za-z\-]*?)\s*(\d.*)$")


def normalise_port(raw: str | None, platform: str) -> str:
    """The short form of an interface name (``GigabitEthernet1/0/5`` -> ``Gi1/0/5``).

    LLDP and CDP print long names, the MAC address table short ones; the neighbours are matched to
    MAC-table ports by this form. Unknown names (``mgmt0``, ``Vlan10``) are returned stripped.
    """
    text = _text(raw)
    match = _PORT_NAME.match(text)
    if match is None:
        return text
    prefix, rest = match.group(1), match.group(2)
    key = prefix.lower()
    if key == "ethernet":
        return f"{'Eth' if 'nxos' in platform else 'Et'}{rest}"
    short = _PORT_PREFIXES.get(key)
    return f"{short}{rest}" if short else text


_LLDP_CODES = {
    "b": "bridge",
    "r": "router",
    "w": "wlan_ap",
    "t": "telephone",
    "c": "docsis",
    "s": "station",
    "p": "repeater",
    "o": "other",
}
# CDP's legacy letter codes differ from LLDP's (S is Switch there, H is Host).
_CDP_CODES = {
    "r": "router",
    "t": "bridge",
    "b": "bridge",
    "s": "bridge",
    "h": "station",
    "p": "telephone",
}
_CDP_WORDS = {
    "router": "router",
    "switch": "bridge",
    "trans-bridge": "bridge",
    "source-route-bridge": "bridge",
    "host": "station",
    "phone": "telephone",
    "repeater": "repeater",
}


def parse_capabilities(raw: str | None, protocol: str) -> tuple[str, ...]:
    """Advertised capabilities as sorted names of a closed vocabulary; unknown words are dropped."""
    found: set[str] = set()
    for token in re.split(r"[,\s]+", _text(raw)):
        if not token:
            continue
        if len(token) == 1:
            # CDP's capital letters are codes too ("R S I"); lower-case "r" there is Repeater.
            table = _CDP_CODES if protocol == "cdp" else _LLDP_CODES
            name = table.get(token.lower())
            if protocol == "cdp" and token == "r":
                name = "repeater"
        else:
            name = _CDP_WORDS.get(token.lower()) if protocol == "cdp" else None
        if name:
            found.add(name)
    return tuple(sorted(found))


def parse_neighbors(
    rows: list[dict[str, Any]], protocol: str, platform: str
) -> list[NeighborEntry]:
    """LLDP / CDP detail rows (ntc-templates) -> entries. Rows without a local port are skipped."""
    entries: list[NeighborEntry] = []
    for row in rows:
        local = _text(row.get("local_interface"))
        if not local:
            continue
        entries.append(
            NeighborEntry(
                port=normalise_port(local, platform),
                neighbor_name=_text(row.get("neighbor_name")) or None,
                neighbor_port=(
                    _text(row.get("neighbor_interface")) or _text(row.get("neighbor_port_id"))
                )
                or None,
                protocol=protocol,
                capabilities=parse_capabilities(row.get("capabilities"), protocol),
            )
        )
    return entries


def parse_channels(rows: list[dict[str, Any]], platform: str) -> dict[str, str]:
    """Port-channel summary rows -> ``{member port: bundle}`` (both in the short form)."""
    members: dict[str, str] = {}
    for row in rows:
        bundle = normalise_port(row.get("bundle_name"), platform)
        raw_members = row.get("member_interface")
        if not bundle or not isinstance(raw_members, list):
            continue
        for member in raw_members:
            name = normalise_port(member, platform)
            if name and name != "--" and name[0].isalpha():
                members[name] = bundle
    return members


def combine_neighbor_statuses(statuses: tuple[CollectionStatus, ...]) -> CollectionStatus:
    """One status for the LLDP and CDP commands of a device.

    Output that is not a table (``no_template``) in either one is not trusted, so the neighbours
    of the device are not replaced; otherwise ``ok`` if either was read, else ``not_supported``.
    """
    if STATUS_NO_TEMPLATE in statuses:
        return STATUS_NO_TEMPLATE
    if STATUS_OK in statuses:
        return STATUS_OK
    return STATUS_NOT_SUPPORTED


def svi_vlan(interface: str | None) -> str | None:
    """VLAN id of an SVI interface name (``Vlan10``, ``Vl10``), else ``None``."""
    if not interface:
        return None
    match = _SVI.match(interface.strip())
    return match.group(1) if match else None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _valid_ip(value: Any) -> str | None:
    try:
        return str(ipaddress.ip_address(_text(value)))
    except ValueError:
        return None


def parse_arp(rows: list[dict[str, Any]], *, vrf: str | None) -> list[ArpEntry]:
    """ARP rows (ntc-templates ``show ip arp``) -> entries. Rows without a valid IP are skipped."""
    entries: list[ArpEntry] = []
    for row in rows:
        ip = _valid_ip(row.get("ip_address"))
        if ip is None:
            continue
        interface = _text(row.get("interface")) or None
        entries.append(
            ArpEntry(
                ip_address=ip,
                mac_address=normalise_mac(_text(row.get("mac_address"))),
                interface=interface,
                vrf=vrf,
                vlan=svi_vlan(interface),
            )
        )
    return entries


def _vlan(value: Any) -> str | None:
    # NX-OS prefixes the VLAN with a marker column ("*   30"); keep the last token.
    tokens = _text(value).split()
    return tokens[-1] if tokens else None


def _port(row: dict[str, Any]) -> str | None:
    raw = row.get("destination_port")
    if raw is None:
        raw = row.get("ports")
    if isinstance(raw, list):
        first = next((_text(item) for item in raw if _text(item)), "")
        return first or None
    return _text(raw) or None


def parse_mac_table(rows: list[dict[str, Any]]) -> list[MacEntry]:
    """MAC address table rows (IOS and NX-OS field names) -> entries. Invalid MACs are skipped."""
    entries: list[MacEntry] = []
    for row in rows:
        mac = normalise_mac(_text(row.get("destination_address") or row.get("mac_address")))
        if mac is None:
            continue
        entries.append(MacEntry(mac_address=mac, vlan=_vlan(row.get("vlan_id")), port=_port(row)))
    return entries


def _vrf_names_from_rows(rows: list[Any]) -> list[str]:
    return [_text(row.get("name")) for row in rows if isinstance(row, dict)]


def _vrf_names_from_text(output: str) -> list[str]:
    names: list[str] = []
    header_seen = False
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not header_seen:
            header_seen = stripped.lower().startswith("name")
            continue
        # Continuation lines list only another interface (deeply indented, one column).
        columns = stripped.split()
        indent = len(line) - len(line.lstrip())
        if len(columns) >= 2 and indent <= _MAX_VRF_INDENT:
            names.append(columns[0])
    return names


def parse_vrf_names(output: str) -> list[str]:
    """VRF names from ``show vrf`` (TextFSM JSON or raw text), without ``default``, unique."""
    if not output.strip() or find_cli_error(output) is not None:
        return []
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError:
        candidates = _vrf_names_from_text(output)
    else:
        candidates = _vrf_names_from_rows(decoded) if isinstance(decoded, list) else []
    unique: list[str] = []
    for name in candidates:
        if _SAFE_VRF_NAME.match(name) and name.lower() != _DEFAULT_VRF and name not in unique:
            unique.append(name)
    return unique


# What an empty table still prints: a header (or "no entries" text). Anything else is not
# a table, and must not be mistaken for "zero rows".
_TABLE_HINTS: dict[str, re.Pattern[str]] = {
    CMD_ARP: re.compile(r"\b(?:address|hardware addr|mac address)\b", re.IGNORECASE),
    CMD_MAC_TABLE: re.compile(r"\b(?:mac address|destination address)\b", re.IGNORECASE),
    CMD_VRF_LIST: re.compile(r"^\s*name\b", re.IGNORECASE | re.MULTILINE),
}
# An entry. Netmiko returns the raw text when TextFSM yields no records, which also happens for
# a table that still has entries (a header the template does not know): that is not "empty".
_IP_TOKEN = re.compile(
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b|\b[0-9a-f]{1,4}(?::[0-9a-f]{0,4}){2,}\b", re.IGNORECASE
)
_MAC_TOKEN = re.compile(
    r"\b[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\b|\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b",
    re.IGNORECASE,
)
_ENTRY_TOKENS: dict[str, re.Pattern[str]] = {CMD_ARP: _IP_TOKEN, CMD_MAC_TABLE: _MAC_TOKEN}
# Neighbours: only an explicit "0 entries" line is an empty table. Blank output is not (a dropped
# session prints nothing too, and "no neighbours" would replace the stored ones).
_ZERO_NEIGHBORS = re.compile(r"total (?:cdp )?entries displayed\s*:\s*0\b", re.IGNORECASE)
_ZERO_CHANNELS = re.compile(r"number of channel-groups in use\s*:\s*0\b", re.IGNORECASE)
_TABLE_HINTS[CMD_LLDP] = _ZERO_NEIGHBORS
_TABLE_HINTS[CMD_CDP] = _ZERO_NEIGHBORS
_TABLE_HINTS[CMD_CHANNELS_IOS] = _ZERO_CHANNELS
_TABLE_HINTS[CMD_CHANNELS_NXOS] = _ZERO_CHANNELS
# The protocol is switched off on the device: the table is missing, not empty.
_PROTOCOL_OFF = re.compile(
    r"\b(?:lldp|cdp)\b[^\n]*\bnot (?:enabled|running|active)\b"
    r"|\bnot (?:enabled|running)\b[^\n]*\b(?:lldp|cdp)\b",
    re.IGNORECASE,
)


def _base_command(command: str) -> str:
    return command.split(" vrf ")[0]


def _blank_means_empty(command: str) -> bool:
    """Only these print nothing at all when empty (no VRFs; an empty VRF). The default ARP and
    MAC tables always print a header, so blank output there is a dropped session."""
    return command == CMD_VRF_LIST or command.startswith(f"{CMD_ARP} vrf ")


def _looks_like_empty_table(raw: str, command: str) -> bool:
    base = _base_command(command)
    hint = _TABLE_HINTS.get(base)
    if hint is None or hint.search(raw) is None:
        return False
    entry = _ENTRY_TOKENS.get(base)
    return entry is None or entry.search(raw) is None


def _has_template(platform: str, command: str) -> bool:
    try:
        parse_output(platform=platform, command=command, data="")
    except ParsingException:
        return False  # ntc-templates has no template for this platform and command
    return True


def _template_exists(platform: str, command: str) -> bool:
    if _has_template(platform, command):
        return True
    # Netmiko retries IOS-XE output against the IOS templates.
    return "cisco_xe" in platform and _has_template("cisco_ios", command)


def classify_output(raw: str, *, platform: str, command: str) -> OutputClass:
    """Classify one command's output: parsed rows, an empty table, a refusal or no template."""
    if not raw.strip():
        return OutputClass(STATUS_OK if _blank_means_empty(command) else STATUS_NO_TEMPLATE)
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        if find_cli_error(raw) is not None:
            return OutputClass(STATUS_NOT_SUPPORTED)
        if command in NEIGHBOR_COMMANDS and _PROTOCOL_OFF.search(raw):
            return OutputClass(STATUS_NOT_SUPPORTED)
        if _template_exists(platform, command) and _looks_like_empty_table(raw, command):
            return OutputClass(STATUS_OK)
        return OutputClass(STATUS_NO_TEMPLATE)
    if not isinstance(decoded, list):
        return OutputClass(STATUS_NO_TEMPLATE)
    return OutputClass(STATUS_OK, [row for row in decoded if isinstance(row, dict)])
