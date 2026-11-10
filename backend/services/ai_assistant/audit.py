"""Audit trail for assistant turns (doc/ai_integration/AI_ASSISTANT.md §5).

One log line per chat turn: who, which surface, which provider and model, which tools ran, which
data classes were withheld, token usage and the outcome. Never any prompt, tool result or content.
Applied changes are audited separately by the existing ``WorkflowChange`` path.
"""

from __future__ import annotations

import hashlib
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
    # Ids of the runs / artifacts / inventories the tools touched (ids only).
    refs: set[str] = field(default_factory=set)

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
            "withheld=%s refs=%s input_tokens=%s output_tokens=%s outcome=%s",
            c.user_id,
            c.surface,
            c.provider,
            c.model,
            ",".join(self.tools) or "-",
            ",".join(sorted(self.withheld)) or "-",
            ",".join(sorted(self.refs)) or "-",
            self.input_tokens,
            self.output_tokens,
            self.outcome,
        )


def log_device_command(
    *,
    user_id: int,
    device_id: str,
    command_hash: str,
    outcome: str,
    handle: str | None,
) -> None:
    """One line per confirmed device command: ids and a hash of the commands, never content."""
    logger.info(
        "ai_assistant_device_command user_id=%s device_id=%s commands=%s outcome=%s handle=%s",
        user_id,
        device_id,
        command_hash,
        outcome,
        handle or "-",
    )


def log_config_download(*, user_id: int, device: str, handle: str) -> None:
    """One line per config download: who, which device and handle, never the configuration."""
    logger.info(
        "ai_assistant_config_download user_id=%s device=%s handle=%s", user_id, device, handle
    )


def log_dns_lookup(*, query: str, status: str) -> None:
    """One line per DNS lookup: a hash of the query (never the name), so a lookup used to carry
    data out can be matched to a suspect name afterwards."""
    digest = hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]
    logger.info("ai_assistant_dns_lookup query=%s status=%s", digest, status)
