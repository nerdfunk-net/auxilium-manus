"""The run inputs of a confirmed released-workflow start (doc/AI_TOOL_CHAIN.md §16).

Pure: joins what the signed proposal holds (the model's plain inputs and the resolved devices) with
what only the confirming user supplies (a credential per declared credential input, and an optional
device type for addresses outside the inventory). The devices input and the credential inputs are
filled here and nowhere else, so neither the model nor a tampered request can write them directly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.workflow.device_lines import device_line, parse_ipv4_literal

MAX_DEVICES = 20


class ReleasedRunError(ValueError):
    """A start that cannot be built; the message is safe to show to the user."""


@dataclass(frozen=True)
class ProposedDevice:
    """A device the assistant named: an inventory device, or a bare IPv4 address."""

    ip: str
    name: str | None = None
    in_inventory: bool = True
    network_driver: str | None = None
    platform: str | None = None

    @property
    def label(self) -> str:
        return self.name or self.ip


def device_lines(devices: Sequence[ProposedDevice], free_ip_driver: str | None) -> str:
    """One Get from User line per device.

    An address outside the inventory has no name and no known driver: it gets the type the user
    chose on the card, or none (the workflow's default driver then applies).
    """
    lines: list[str] = []
    for device in devices:
        if parse_ipv4_literal(device.ip) is None:
            raise ReleasedRunError(f"{device.label} has no valid IPv4 address")
        line = (
            device_line(
                name=device.name,
                ip=device.ip,
                network_driver=device.network_driver,
                platform=device.platform,
            )
            if device.in_inventory
            else device_line(name=None, ip=device.ip, network_driver=free_ip_driver, platform=None)
        )
        if line is None:
            raise ReleasedRunError(f"{device.label} cannot be passed to the workflow")
        lines.append(line)
    return "\n".join(lines)


def build_run_inputs(
    *,
    devices_input: str | None,
    credential_inputs: Iterable[str],
    allow_free_ip: bool,
    model_inputs: Mapping[str, Any],
    devices: Sequence[ProposedDevice],
    credentials: Mapping[str, str],
    free_ip_driver: str | None,
) -> dict[str, Any]:
    """The run inputs to start with, or ``ReleasedRunError``."""
    wanted = list(credential_inputs)
    reserved = {*wanted, *([devices_input] if devices_input else [])}
    clash = sorted(reserved & set(model_inputs))
    if clash:
        raise ReleasedRunError(f"{', '.join(clash)} cannot be set by the assistant")

    if set(credentials) != set(wanted):
        missing = sorted(set(wanted) - set(credentials))
        extra = sorted(set(credentials) - set(wanted))
        if missing:
            raise ReleasedRunError(f"Choose a credential for: {', '.join(missing)}")
        raise ReleasedRunError(f"Not a credential input of this workflow: {', '.join(extra)}")
    blank = sorted(name for name, value in credentials.items() if not str(value).strip())
    if blank:
        raise ReleasedRunError(f"Choose a credential for: {', '.join(blank)}")

    if devices_input is None:
        if devices:
            raise ReleasedRunError("This workflow does not take devices")
    else:
        if not devices:
            raise ReleasedRunError("This workflow needs at least one device")
        if len(devices) > MAX_DEVICES:
            raise ReleasedRunError(f"At most {MAX_DEVICES} devices can be started at once")
        if not allow_free_ip and any(not d.in_inventory for d in devices):
            raise ReleasedRunError("This workflow only accepts devices from the inventory")

    inputs: dict[str, Any] = dict(model_inputs)
    inputs.update({name: str(value).strip() for name, value in credentials.items()})
    if devices_input is not None:
        inputs[devices_input] = device_lines(devices, free_ip_driver)
    return inputs
