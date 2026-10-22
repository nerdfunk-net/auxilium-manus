"""Call a handler on an agent: seal the request, send it, verify and unpack the answer.

``AgentClient`` owns everything that does not depend on the transport: the request limits, the
envelope (so the transport only ever sees ciphertext), checking that the response really answers
this command, and mapping what the agent reports onto the ``AgentCallError`` family.

Protocol (the decrypted payloads)::

    request   {"handler": str, "params": {...}, "inputs": {...}}
    response  {"status": "success", "output": {...}}
              {"status": "error",   "error": {"type": str, "message": str}}
"""

from __future__ import annotations

import json
import math
import re
import uuid
from types import TracebackType
from typing import Any

import redis.asyncio as aioredis

from services.agents.envelope import (
    EnvelopeError,
    EnvelopeExpiredError,
    EnvelopePayloadError,
    open_envelope,
    seal,
)
from services.agents.exceptions import (
    AgentAuthError,
    AgentHandlerError,
    AgentPayloadTooLargeError,
    AgentTimeoutError,
    AgentTransportError,
    AgentValidationError,
)
from services.agents.http_transport import HttpTransport
from services.agents.redis_transport import RedisTransport
from services.agents.source_config_service import AgentConnection
from services.agents.transport import AgentTransport

HANDLER_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
# The envelope outlives the call a little, so a slow but successful answer still verifies.
_ENVELOPE_TTL_MARGIN_SECONDS = 5
_MAX_ERROR_MESSAGE_CHARS = 200


class AgentClient:
    def __init__(self, connection: AgentConnection, transport: AgentTransport) -> None:
        self._connection = connection
        self._transport = transport

    async def invoke(
        self,
        handler: str,
        params: dict[str, Any],
        inputs: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Run *handler* on the agent and return its JSON ``output`` object."""
        if not HANDLER_NAME_PATTERN.fullmatch(handler or ""):
            raise AgentValidationError(
                "handler must start with a letter and use only letters, digits, '_', '.', '-' "
                "(max 64 characters)"
            )
        conn = self._connection
        effective_timeout = min(timeout or conn.max_timeout_seconds, conn.max_timeout_seconds)

        payload = {"handler": handler, "params": params, "inputs": inputs}
        try:
            size = len(json.dumps(payload, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise AgentValidationError("request data is not JSON serialisable") from exc
        if size > conn.max_request_bytes:
            raise AgentPayloadTooLargeError(
                f"request is {size} bytes, above the agent limit of {conn.max_request_bytes}"
            )

        command_id = uuid.uuid4().hex
        request = seal(
            payload,
            secret=conn.secret,
            agent_id=conn.agent_id,
            command_id=command_id,
            direction="request",
            ttl_seconds=math.ceil(effective_timeout) + _ENVELOPE_TTL_MARGIN_SECONDS,
        )
        response = await self._transport.call(request, timeout=effective_timeout)
        try:
            opened = open_envelope(
                response,
                secret=conn.secret,
                expected_agent_id=conn.agent_id,
                expected_direction="response",
                expected_command_id=command_id,
            )
        except EnvelopeExpiredError as exc:
            # The answer verified as far as we got but arrived outside its window (a very slow
            # handler, or clocks that disagree). That is a lost answer for this device, not
            # evidence of a wrong secret, so it must not abort the other devices.
            raise AgentTimeoutError("agent answer arrived after it had expired") from exc
        except EnvelopePayloadError as exc:
            raise AgentTransportError(f"agent answer is unusable: {exc}") from exc
        except EnvelopeError as exc:
            raise AgentAuthError(f"agent response failed verification: {exc}") from exc
        return _unpack(opened.payload)

    async def aclose(self) -> None:
        await self._transport.aclose()

    async def __aenter__(self) -> AgentClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


def _unpack(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    if status == "success":
        output = payload.get("output")
        if not isinstance(output, dict):
            raise AgentTransportError("agent answered success without a JSON object output")
        return output
    if status == "error":
        error = payload.get("error")
        if not isinstance(error, dict):
            raise AgentTransportError("agent reported an error without details")
        error_type = str(error.get("type") or "Error")[:64]
        message = str(error.get("message") or "")[:_MAX_ERROR_MESSAGE_CHARS]
        raise AgentHandlerError(error_type, message)
    raise AgentTransportError("agent answered with an unknown status")


def build_agent_client(connection: AgentConnection, *, redis_url: str) -> AgentClient:
    """Pick the transport the source is configured for."""
    transport: AgentTransport
    if connection.transport == "http":
        if not connection.url:
            raise AgentValidationError("An agent with the http transport needs a URL")
        transport = HttpTransport(
            url=connection.url, agent_id=connection.agent_id, secret=connection.secret
        )
    else:
        transport = RedisTransport(
            aioredis.from_url(redis_url, decode_responses=True), agent_id=connection.agent_id
        )
    return AgentClient(connection, transport)
