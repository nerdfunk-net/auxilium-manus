"""``propose_device_command``: ask the user to run read-only commands on a device (§29 step 4).

A proposal, never an execution. The tool checks the commands against the read-only policy, finds the
device by name in the inventory the user may read, and hands the client a card with the exact device
and commands plus a signed token. Only the user's click (``POST /ai/exec/device-command``) runs
anything, and that endpoint checks everything again. The model is told it was not run and never
receives the host or the token.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from services.ai_assistant.command_policy import (
    MAX_COMMAND_CHARS,
    MAX_COMMANDS,
    CommandNotAllowedError,
    check_commands,
)
from services.ai_assistant.device_access import (
    DEVICE_DRIVERS,
    DeviceAccessError,
    DeviceResolver,
    driver_known,
)
from services.ai_assistant.device_token import issue_token
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput

# Key of the ``DeviceResolver`` in ``ToolContext.extras``; the surface builder puts it there.
DEVICE_RESOLVER_KEY = "device_resolver"

DeviceName = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9._-]{1,100}$")
]


class ProposeDeviceCommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device: DeviceName = Field(description="Device name exactly as in the inventory, e.g. 'LAB'")
    commands: list[Annotated[str, Field(min_length=1, max_length=MAX_COMMAND_CHARS * 2)]] = Field(
        min_length=1,
        max_length=MAX_COMMANDS,
        description="Read-only show commands: ['show running-config'] or ['show startup-config']",
    )


async def _propose_device_command(ctx: ToolContext, args: ProposeDeviceCommandInput) -> ToolOutput:
    try:
        commands = check_commands(args.commands)
    except CommandNotAllowedError as exc:
        return ToolOutput(
            f"Command refused: {exc}. Only full, read-only 'show' commands are allowed.",
            is_error=True,
        )
    resolver: DeviceResolver = ctx.extras[DEVICE_RESOLVER_KEY]
    try:
        device = await resolver.resolve(args.device)
    except DeviceAccessError as exc:
        return ToolOutput(str(exc), is_error=True)
    token, expires_at = issue_token(
        user_id=ctx.user_id,
        source_id=device.source_id,
        device_id=device.device_id,
        device_name=device.name,
        host=device.host,
        commands=commands,
    )
    ctx.audit_refs.add(f"device:{device.device_id}")
    known_driver = driver_known(device)
    proposal = {
        "kind": "device_command",
        "token": token,
        "expires_at": expires_at,
        "device": {
            "id": device.device_id,
            "name": device.name,
            "host": device.host,
            "platform": device.platform,
        },
        "commands": commands,
        # When the inventory's platform names no Netmiko driver, the card asks the user for the
        # device type (from this closed list); the model has no say in it.
        "driver_known": known_driver,
        "driver_choices": list(DEVICE_DRIVERS),
    }
    message = (
        f"The command(s) were shown to the user for device {device.name} with Run/Reject. They are "
        "NOT run yet; do not say they were and do not guess the output. The user chooses the SSH "
        "credential and confirms. When they run it, the output is stored and you get its handle in "
        "their next message: read it with fetch_slice. Briefly say what you asked to run and why."
    )
    if not known_driver:
        message += (
            " The inventory does not say which device type this is, so the card also asks the user "
            "to choose the device type."
        )
    return ToolOutput(message, proposal=proposal)


_DESCRIPTION = (
    "Ask the user to run read-only 'show' commands on one device, for live data the Batfish model "
    "does not have (for example the running or startup config). This only proposes: nothing runs "
    "until the user confirms in the card. Use full commands such as 'show running-config' or "
    "'show startup-config'; configuration, reload, copy, ping and abbreviations are refused."
)


def build_device_tools() -> list[Tool]:
    return [
        Tool(
            "propose_device_command",
            _DESCRIPTION,
            ProposeDeviceCommandInput,
            _propose_device_command,
        )
    ]
