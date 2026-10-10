"""Audit trail for assistant turns (doc/ai_integration/AI_ASSISTANT.md §5).

One log line per chat turn: who, which surface, which provider and model, which tools ran, which
data classes were withheld, token usage and the outcome. Never any prompt, tool result or content.
Applied changes are audited separately by the existing ``WorkflowChange`` path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from services.ai_assistant.events import ChatEvent

logger = logging.getLogger("ai_assistant.audit")


@dataclass(frozen=True)
class AuditContext:
    user_id: int
    surface: str
    provider: str
    model: str


@dataclass
class TurnAudit:
    """Collects what happened during one turn from the event stream."""

    context: AuditContext
    tools: list[str] = field(default_factory=list)
    withheld: set[str] = field(default_factory=set)
    input_tokens: int = 0
    output_tokens: int = 0
    outcome: str = "ok"

    def observe(self, event: ChatEvent) -> None:
        data = event.data
        if event.event == "tool" and data.get("status") == "running":
            self.tools.append(str(data.get("name")))
        elif event.event == "tool":
            self.withheld.update(str(w) for w in data.get("withheld", []))
        elif event.event == "usage":
            self.input_tokens = int(data.get("input_tokens", 0))
            self.output_tokens = int(data.get("output_tokens", 0))
        elif event.event == "error":
            self.outcome = f"error:{data.get('code', 'unknown')}"

    def log(self) -> None:
        c = self.context
        logger.info(
            "ai_assistant_turn user_id=%s surface=%s provider=%s model=%s tools=%s "
            "withheld=%s input_tokens=%s output_tokens=%s outcome=%s",
            c.user_id,
            c.surface,
            c.provider,
            c.model,
            ",".join(self.tools) or "-",
            ",".join(sorted(self.withheld)) or "-",
            self.input_tokens,
            self.output_tokens,
            self.outcome,
        )
