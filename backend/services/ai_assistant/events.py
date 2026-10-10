"""Events the chat stream emits to the client (serialised as SSE by the router)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatEvent:
    """``event`` is the SSE event name; ``data`` its JSON payload."""

    event: str
    data: dict[str, Any]
