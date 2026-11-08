"""POST /v1/learn-replay -- learn a feature from already-fetched command output.

No device connection: the commands' text is replayed through a Unicon mock device (see
``replay_mock``), so Genie's own Ops class builds the ``info`` tree, the same model ``pyats learn``
gives. The result is a snapshot payload (``{"info", "_exclude"}``) that POST /v1/diff accepts.

The work runs in a child process with a time limit, so a hung or crashing mock cannot block the
shim; the child is killed at the limit. Error text from Genie is never passed on (it can quote CLI
output): only a fixed sentence.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError

from app.auth import require_bearer_token
from app.replay_mock import MAX_COMMANDS, MAX_OUTPUT_CHARS, ReplayInputError, validate

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_bearer_token)])

REPLAY_TIMEOUT_SECONDS = 90.0
# The most the endpoint reads from the socket: every output may be MAX_OUTPUT_CHARS in all, and
# JSON escapes and non-ASCII text make the body larger than the text it carries.
MAX_BODY_BYTES = 4 * MAX_OUTPUT_CHARS
REPLAY_FAILED = "Genie could not learn the feature from this output"
REPLAY_TIMED_OUT = "Learning the feature took too long"
# At most this many replays at once: each starts a process.
_slots = asyncio.Semaphore(2)


class ReplayCommand(BaseModel):
    command: str = Field(..., min_length=1, max_length=200)
    output: str = Field(..., max_length=MAX_OUTPUT_CHARS)


class ReplayRequest(BaseModel):
    os: str = Field(..., min_length=1, max_length=20)
    feature: str = Field(..., min_length=1, max_length=20)
    commands: list[ReplayCommand] = Field(..., min_length=1, max_length=MAX_COMMANDS)


class ReplayResponse(BaseModel):
    payload: dict[str, Any] | None = None
    error: str | None = None


def _last_json_line(text: str) -> dict[str, Any] | None:
    """The last line of ``text`` that is a JSON object. Lines that only look like one (Genie logs
    braces too) are skipped, so a good result is never hidden by a later odd line."""
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _kill_group(process: asyncio.subprocess.Process) -> None:
    """Kill the worker and everything it started (it leads its own process group)."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        process.kill()


async def _run_worker(request: dict[str, Any]) -> ReplayResponse:
    # The working directory belongs to this process, not to the worker: a worker killed at the
    # limit cannot clean up after itself, and its files hold the replayed device output.
    workdir = tempfile.mkdtemp(prefix="replay-")
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.replay_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(
                    json.dumps({**request, "workdir": workdir}).encode()
                ),
                timeout=REPLAY_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            logger.warning(
                "learn replay timed out os=%s feature=%s",
                request["os"],
                request["feature"],
            )
            return ReplayResponse(error=REPLAY_TIMED_OUT)
        answer = _last_json_line(stdout.decode(errors="replace"))
        if process.returncode != 0 or not answer or not answer.get("ok"):
            return ReplayResponse(error=REPLAY_FAILED)
        payload = answer.get("payload")
        if not isinstance(payload, dict):
            return ReplayResponse(error=REPLAY_FAILED)
        return ReplayResponse(payload=payload)
    finally:
        # Also when the request is cancelled (the caller went away) or anything else went wrong.
        if process is not None and process.returncode is None:
            _kill_group(process)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(process.wait(), timeout=5)
        shutil.rmtree(workdir, ignore_errors=True)


async def _read_body(request: Request) -> bytes:
    """The request body, never more than ``MAX_BODY_BYTES`` (read from the socket, not after it)."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(413, "The request is too large")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise HTTPException(413, "The request is too large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/v1/learn-replay", response_model=ReplayResponse)
async def learn_replay(request: Request) -> ReplayResponse:
    # Authentication already ran (router dependency) before a byte of the body is read.
    raw = await _read_body(request)
    try:
        body = ReplayRequest.model_validate_json(raw)
    except ValidationError as exc:
        # Fixed text: the default error body would quote the submitted output.
        raise HTTPException(422, "The request body is not valid") from exc
    commands = [c.model_dump() for c in body.commands]
    try:
        validate(body.os, body.feature, commands)
    except ReplayInputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    logger.info(
        "learn replay received os=%s feature=%s commands=%d",
        body.os,
        body.feature,
        len(commands),
    )
    async with _slots:
        result = await _run_worker(
            {"os": body.os, "feature": body.feature, "commands": commands}
        )
    logger.info("learn replay finished ok=%s", result.error is None)
    return result
