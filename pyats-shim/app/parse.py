"""POST /v1/parse -- Genie offline parse of already-fetched command output.

Pure in-process computation, no subprocess/testbed/device I/O -- unlike
/v1/jobs this never touches JobRunner and never opens an SSH connection. This
is the same mechanism the `genie parse <file> --os <os>` CLI tool uses: build
an unconnected Genie ``Device`` for the given ``os`` and call
``device.parse(command, output=raw_text)``, which looks up the registered
parser for that os/command pair and parses the caller-supplied text directly.

Callers (e.g. the run-command workflow step) already have raw CLI output --
fetched however they like (Netmiko, in this codebase's case) -- and want it
Genie-parsed without a second live device connection.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import require_bearer_token

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_bearer_token)])

# One command may take this long. Genie parsing is CPU-bound Python that cannot be interrupted, so
# a slow parse runs in a worker thread and is *abandoned* at the limit: the event loop stays free
# for the shim's other requests and the caller gets an answer. (The thread finishes on its own.)
PARSE_COMMAND_TIMEOUT_SECONDS = 30.0
PARSE_TIMED_OUT = "Parsing took too long"


class ParseCommandInput(BaseModel):
    command: str = Field(..., min_length=1)
    output: str


class ParseDeviceInput(BaseModel):
    os: str = Field(..., min_length=1)
    commands: list[ParseCommandInput] = Field(..., min_length=1)


class ParseRequest(BaseModel):
    devices: dict[str, ParseDeviceInput] = Field(..., min_length=1)


class ParseCommandResult(BaseModel):
    parsed: dict | list | None = None
    error: str | None = None


class ParseDeviceResult(BaseModel):
    commands: dict[str, ParseCommandResult]


class ParseResponse(BaseModel):
    results: dict[str, ParseDeviceResult]


def _parse_one(*, os_name: str, command: str, output: str) -> ParseCommandResult:
    from genie.conf.base import (
        Device,
    )  # lazy import -- genie only exists inside the container

    try:
        device = Device("shim-parse", os=os_name)
        parsed = device.parse(command, output=output)
    except Exception as exc:  # noqa: BLE001 - unknown command/no parser, not a server bug
        return ParseCommandResult(error=str(exc))
    return ParseCommandResult(parsed=parsed)


async def _parse_one_bounded(
    *, os_name: str, command: str, output: str
) -> ParseCommandResult:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _parse_one, os_name=os_name, command=command, output=output
            ),
            timeout=PARSE_COMMAND_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("parse timed out os=%s", os_name)
        return ParseCommandResult(error=PARSE_TIMED_OUT)


@router.post("/v1/parse", response_model=ParseResponse)
async def parse_output(body: ParseRequest) -> ParseResponse:
    device_names = list(body.devices.keys())
    command_count = sum(len(device.commands) for device in body.devices.values())
    logger.info(
        "parse request received devices=%s commands=%d", device_names, command_count
    )

    results: dict[str, ParseDeviceResult] = {}
    for device_id, device_input in body.devices.items():
        commands: dict[str, ParseCommandResult] = {}
        for command_input in device_input.commands:
            commands[command_input.command] = await _parse_one_bounded(
                os_name=device_input.os,
                command=command_input.command,
                output=command_input.output,
            )
        results[device_id] = ParseDeviceResult(commands=commands)

    error_count = sum(
        1
        for device_result in results.values()
        for command_result in device_result.commands.values()
        if command_result.error
    )
    logger.info(
        "parse request finished devices=%d commands=%d errors=%d",
        len(results),
        command_count,
        error_count,
    )
    return ParseResponse(results=results)
