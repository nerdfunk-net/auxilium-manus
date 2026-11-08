"""Collect the ARP / MAC table of one device over a pooled SSH session.

Phase 1 sends VRF discovery, ARP and the MAC table in one call with ``fail_on_cli_error``
off, so a command the platform refuses (a router has no MAC table) does not stop the others.
Each command is then classified on its own (``parsing.classify_output``). Phase 2 asks for
the ARP table of every discovered VRF. A connection, authentication or timeout error fails
the whole device.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from models.client_data import (
    ClientCollectionStatus,
    ClientIpRow,
    ClientMacRow,
    ClientNeighborRow,
    CollectionStatus,
    TooManyRowsError,
    VrfResult,
    check_row_cap,
)
from models.failure import FailureInfo
from services.network.netmiko.connection import CommandResult
from services.network.netmiko.service import NetmikoService
from workflow_steps.collect_client_data.commands import (
    CMD_ARP,
    CMD_CDP,
    CMD_LLDP,
    CMD_MAC_TABLE,
    CMD_VRF_LIST,
    NEIGHBOR_COMMANDS,
    arp_in_vrf,
    channel_command,
)
from workflow_steps.collect_client_data.options import CollectOptions
from workflow_steps.collect_client_data.parsing import (
    STATUS_NO_TEMPLATE,
    STATUS_NOT_SUPPORTED,
    STATUS_OK,
    STATUS_SKIPPED,
    NeighborEntry,
    classify_output,
    combine_neighbor_statuses,
    parse_arp,
    parse_channels,
    parse_mac_table,
    parse_neighbors,
    parse_vrf_names,
)

logger = logging.getLogger(__name__)


class CollectionError(Exception):
    """A device could not be collected; carries the closed-vocabulary failure record."""

    def __init__(self, code: str, message: str, failure: FailureInfo | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.failure = failure


@dataclass(frozen=True)
class DeviceTarget:
    host: str
    device_type: str
    network_driver: str | None
    platform: str | None
    username: str
    password: str
    credential_reference: str


@dataclass(frozen=True)
class DeviceCollection:
    ip_rows: tuple[ClientIpRow, ...]
    mac_rows: tuple[ClientMacRow, ...]
    status: ClientCollectionStatus
    vrfs: tuple[str, ...]
    neighbor_rows: tuple[ClientNeighborRow, ...] = ()


def phase_one_commands(options: CollectOptions, device_type: str = "cisco_ios") -> list[str]:
    commands: list[str] = []
    if options.collect_vrfs:
        commands.append(CMD_VRF_LIST)
    if options.collect_ip_address:
        commands.append(CMD_ARP)
    if options.collect_mac_address:
        commands.append(CMD_MAC_TABLE)
    if options.collect_neighbors:
        # LLDP and CDP, and the port-channels that map member ports to their bundle.
        commands.extend([*NEIGHBOR_COMMANDS, channel_command(device_type)])
    return commands


async def _send(
    netmiko: NetmikoService, target: DeviceTarget, commands: list[str], options: CollectOptions
) -> CommandResult:
    result = await netmiko.send_commands(
        host=target.host,
        network_driver=target.network_driver,
        platform=target.platform,
        username=target.username,
        password=target.password,
        commands=commands,
        credential_reference=target.credential_reference,
        use_textfsm=True,
        device_type=target.device_type,
        read_timeout=options.read_timeout,
        fail_on_cli_error=False,
        retry=options.retry,
    )
    if not result.success:
        raise CollectionError(
            "command_failed", result.error or "Command execution failed", result.failure
        )
    return result


def _classify(
    outputs: dict[str, str], command: str, device_type: str
) -> tuple[CollectionStatus, list[dict[str, Any]]]:
    result = classify_output(outputs.get(command, ""), platform=device_type, command=command)
    return result.status, result.rows


async def _collect_vrf_arp(
    netmiko: NetmikoService,
    target: DeviceTarget,
    vrfs: list[str],
    options: CollectOptions,
    *,
    max_rows: int,
    rows_so_far: int,
) -> tuple[list[ClientIpRow], list[VrfResult]]:
    """ARP entries of each VRF, one command per round trip on the same pooled session.

    One command at a time, so that reading stops at the row cap instead of fetching every VRF
    table first. Also returns what each VRF gave, so an empty VRF can be told from one the
    device refused.
    """
    rows: list[ClientIpRow] = []
    results: list[VrfResult] = []
    for vrf in vrfs:
        command = arp_in_vrf(vrf)
        result = await _send(netmiko, target, [command], options)
        status, raw_rows = _classify(result.command_outputs, command, target.device_type)
        if status != STATUS_OK:
            # One VRF the device cannot show must not discard the others.
            logger.debug("per-VRF ARP not usable status=%s", status)
            results.append(VrfResult(name=vrf, status=status))
            continue
        # Counted before parsing, over everything read so far, so a huge VRF is not parsed.
        _enforce_row_cap(rows_so_far + len(rows) + len(raw_rows), 0, max_rows)
        vrf_rows = _to_ip_rows(raw_rows, vrf)
        rows.extend(vrf_rows)
        results.append(VrfResult(name=vrf, status=STATUS_OK, rows=len(vrf_rows)))
    return rows, results


def _collect_neighbors(
    outputs: dict[str, str], device_type: str
) -> tuple[CollectionStatus, list[ClientNeighborRow]]:
    """LLDP and CDP neighbours of the ports, each with the port-channel its port belongs to.

    Neighbour data only sharpens the uplink guess, so it never fails the device: output that is
    not a table gives status ``no_template`` and no rows (and the older neighbours stay current).
    """
    statuses: list[CollectionStatus] = []
    entries: list[NeighborEntry] = []
    for command, protocol in ((CMD_LLDP, "lldp"), (CMD_CDP, "cdp")):
        status, raw_rows = _classify(outputs, command, device_type)
        statuses.append(status)
        if status == STATUS_OK:
            entries.extend(parse_neighbors(raw_rows, protocol, device_type))
    combined = combine_neighbor_statuses(tuple(statuses))
    if combined != STATUS_OK:
        return combined, []
    channel_status, raw_channels = _classify(outputs, channel_command(device_type), device_type)
    channels = parse_channels(raw_channels, device_type) if channel_status == STATUS_OK else {}
    if channel_status != STATUS_OK:
        logger.debug("port-channel table not usable status=%s", channel_status)
    rows = [
        ClientNeighborRow(
            port=entry.port,
            channel=channels.get(entry.port),
            neighbor_name=entry.neighbor_name,
            neighbor_port=entry.neighbor_port,
            protocol=entry.protocol,  # type: ignore[arg-type]
            capabilities=",".join(entry.capabilities),
            is_infrastructure=entry.is_infrastructure,
        )
        for entry in entries
    ]
    return combined, rows


def _to_ip_rows(raw_rows: list[dict[str, Any]], vrf: str | None) -> list[ClientIpRow]:
    return [
        ClientIpRow(
            ip_address=entry.ip_address,
            mac_address=entry.mac_address,
            interface=entry.interface,
            vrf=entry.vrf,
            vlan=entry.vlan,
        )
        for entry in parse_arp(raw_rows, vrf=vrf)
    ]


def _require_something(
    options: CollectOptions, arp_status: CollectionStatus, mac_status: CollectionStatus
) -> None:
    """Fail the device rather than store an empty or wrong collection.

    A refused command is expected (a router has no MAC table). Output that is neither a table
    nor a refusal is not: storing it as "no rows" would replace the device's good data.
    """
    requested = []
    if options.collect_ip_address:
        requested.append(arp_status)
    if options.collect_mac_address:
        requested.append(mac_status)
    if STATUS_NO_TEMPLATE in requested:
        raise CollectionError(
            "unparsable_output",
            f"The device output could not be read as a table (arp: {arp_status}, "
            f"mac: {mac_status})",
            FailureInfo(phase="command", kind="invalid_response"),
        )
    if requested and all(status == STATUS_NOT_SUPPORTED for status in requested):
        raise CollectionError(
            "nothing_collected",
            f"The device refused every requested table (arp: {arp_status}, mac: {mac_status})",
            FailureInfo(phase="command", kind="command_error"),
        )


def _enforce_row_cap(ip_count: int, mac_count: int, max_rows: int, neighbor_count: int = 0) -> None:
    """Fail the device before DNS and storage when a table is above the cap."""
    try:
        check_row_cap(ip_count, mac_count, max_rows, neighbor_count)
    except TooManyRowsError as exc:
        raise CollectionError(
            "too_many_rows",
            f"The {exc.table} table has more rows than CLIENT_DATA_MAX_ROWS_PER_TABLE "
            f"({exc.limit}) allows; nothing was stored for this device",
            FailureInfo(phase="command", kind="payload_too_large"),
        ) from exc


async def collect_from_device(
    *, netmiko: NetmikoService, target: DeviceTarget, options: CollectOptions, max_rows: int
) -> DeviceCollection:
    """Collect one device. Raises ``CollectionError`` when nothing usable could be read.

    A table above *max_rows* fails the device (``too_many_rows``) before any DNS lookup.
    """
    first = await _send(netmiko, target, phase_one_commands(options, target.device_type), options)
    outputs = first.command_outputs

    arp_status: CollectionStatus = STATUS_SKIPPED
    mac_status: CollectionStatus = STATUS_SKIPPED
    vrf_status: CollectionStatus = STATUS_SKIPPED
    ip_rows: list[ClientIpRow] = []
    mac_rows: list[ClientMacRow] = []
    vrfs: list[str] = []
    vrf_results: list[VrfResult] | None = None

    if options.collect_ip_address:
        arp_status, raw_rows = _classify(outputs, CMD_ARP, target.device_type)
        _enforce_row_cap(len(raw_rows), 0, max_rows)  # before parsing an oversized table
        ip_rows = _to_ip_rows(raw_rows, None)
    if options.collect_mac_address:
        mac_status, raw_rows = _classify(outputs, CMD_MAC_TABLE, target.device_type)
        _enforce_row_cap(0, len(raw_rows), max_rows)
        mac_rows = [
            ClientMacRow(mac_address=e.mac_address, vlan=e.vlan, port=e.port)
            for e in parse_mac_table(raw_rows)
        ]
    if options.collect_vrfs:
        vrf_status, _ = _classify(outputs, CMD_VRF_LIST, target.device_type)
        vrfs = parse_vrf_names(outputs.get(CMD_VRF_LIST, "")) if vrf_status == STATUS_OK else []
        if vrf_status == STATUS_OK:
            # Found but not (yet) read; replaced below when the per-VRF ARP runs.
            vrf_results = [VrfResult(name=name, status=STATUS_SKIPPED) for name in vrfs]

    neighbor_status: CollectionStatus = STATUS_SKIPPED
    neighbor_rows: list[ClientNeighborRow] = []
    if options.collect_neighbors:
        neighbor_status, neighbor_rows = _collect_neighbors(outputs, target.device_type)

    _require_something(options, arp_status, mac_status)

    if vrfs and arp_status == STATUS_OK:
        vrf_rows, vrf_results = await _collect_vrf_arp(
            netmiko, target, vrfs, options, max_rows=max_rows, rows_so_far=len(ip_rows)
        )
        ip_rows.extend(vrf_rows)

    _enforce_row_cap(len(ip_rows), len(mac_rows), max_rows, len(neighbor_rows))

    logger.info(
        "collected client data arp=%s mac=%s vrf=%s ip_rows=%d mac_rows=%d vrfs=%d",
        arp_status,
        mac_status,
        vrf_status,
        len(ip_rows),
        len(mac_rows),
        len(vrfs),
    )
    return DeviceCollection(
        ip_rows=tuple(ip_rows),
        mac_rows=tuple(mac_rows),
        status=ClientCollectionStatus(
            arp_status=arp_status,
            mac_status=mac_status,
            vrf_status=vrf_status,
            vrf_count=len(vrfs),
            vrfs=vrf_results,
            neighbor_status=neighbor_status,
        ),
        vrfs=tuple(vrfs),
        neighbor_rows=tuple(neighbor_rows),
    )
