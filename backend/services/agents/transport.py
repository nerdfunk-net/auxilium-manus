"""The seam between the agent client and a concrete way of reaching an agent.

A transport moves one sealed request envelope to the agent and returns the sealed response
envelope. It never looks inside (the client owns encryption), so adding a transport later, such
as an agent that polls the app, does not touch the envelope or the step.
"""

from __future__ import annotations

from typing import Any, Protocol


class AgentTransport(Protocol):
    async def call(self, envelope: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        """Deliver *envelope*; return the response envelope.

        Raises ``AgentOfflineError``, ``AgentTimeoutError``, ``AgentAuthError`` or
        ``AgentTransportError``.
        """
        ...

    async def aclose(self) -> None: ...
