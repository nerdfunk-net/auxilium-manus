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
from workflow_steps.collect_client_data.commands import CMD_ARP, CMD_MAC_TABLE, CMD_VRF_LIST

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
        if _template_exists(platform, command) and _looks_like_empty_table(raw, command):
            return OutputClass(STATUS_OK)
        return OutputClass(STATUS_NO_TEMPLATE)
    if not isinstance(decoded, list):
        return OutputClass(STATUS_NO_TEMPLATE)
    return OutputClass(STATUS_OK, [row for row in decoded if isinstance(row, dict)])
