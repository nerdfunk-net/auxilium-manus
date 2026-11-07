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
    CollectionStatus,
)
from models.failure import FailureInfo
from services.network.netmiko.connection import CommandResult
from services.network.netmiko.service import NetmikoService
from workflow_steps.collect_client_data.commands import (
    CMD_ARP,
    CMD_MAC_TABLE,
    CMD_VRF_LIST,
    arp_in_vrf,
)
from workflow_steps.collect_client_data.options import CollectOptions
from workflow_steps.collect_client_data.parsing import (
    STATUS_NO_TEMPLATE,
    STATUS_NOT_SUPPORTED,
    STATUS_OK,
    STATUS_SKIPPED,
    classify_output,
    parse_arp,
    parse_mac_table,
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


def phase_one_commands(options: CollectOptions) -> list[str]:
    commands: list[str] = []
    if options.collect_vrfs:
        commands.append(CMD_VRF_LIST)
    if options.collect_ip_address:
        commands.append(CMD_ARP)
    if options.collect_mac_address:
        commands.append(CMD_MAC_TABLE)
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
    netmiko: NetmikoService, target: DeviceTarget, vrfs: list[str], options: CollectOptions
) -> list[ClientIpRow]:
    """ARP entries of each VRF (one extra round trip on the same pooled session)."""
    commands = {vrf: arp_in_vrf(vrf) for vrf in vrfs}
    result = await _send(netmiko, target, list(commands.values()), options)
    rows: list[ClientIpRow] = []
    for vrf, command in commands.items():
        status, raw_rows = _classify(result.command_outputs, command, target.device_type)
        if status != STATUS_OK:
            # One VRF the device cannot show must not discard the others.
            logger.debug("per-VRF ARP not usable status=%s", status)
            continue
        rows.extend(_to_ip_rows(raw_rows, vrf))
    return rows


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


async def collect_from_device(
    *, netmiko: NetmikoService, target: DeviceTarget, options: CollectOptions
) -> DeviceCollection:
    """Collect one device. Raises ``CollectionError`` when nothing usable could be read."""
    first = await _send(netmiko, target, phase_one_commands(options), options)
    outputs = first.command_outputs

    arp_status: CollectionStatus = STATUS_SKIPPED
    mac_status: CollectionStatus = STATUS_SKIPPED
    vrf_status: CollectionStatus = STATUS_SKIPPED
    ip_rows: list[ClientIpRow] = []
    mac_rows: list[ClientMacRow] = []
    vrfs: list[str] = []

    if options.collect_ip_address:
        arp_status, raw_rows = _classify(outputs, CMD_ARP, target.device_type)
        ip_rows = _to_ip_rows(raw_rows, None)
    if options.collect_mac_address:
        mac_status, raw_rows = _classify(outputs, CMD_MAC_TABLE, target.device_type)
        mac_rows = [
            ClientMacRow(mac_address=e.mac_address, vlan=e.vlan, port=e.port)
            for e in parse_mac_table(raw_rows)
        ]
    if options.collect_vrfs:
        vrf_status, _ = _classify(outputs, CMD_VRF_LIST, target.device_type)
        vrfs = parse_vrf_names(outputs.get(CMD_VRF_LIST, "")) if vrf_status == STATUS_OK else []

    _require_something(options, arp_status, mac_status)

    if vrfs and arp_status == STATUS_OK:
        ip_rows.extend(await _collect_vrf_arp(netmiko, target, vrfs, options))

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
        ),
        vrfs=tuple(vrfs),
    )
