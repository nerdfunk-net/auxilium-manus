"""Pydantic models for saved AI assistant conversations (doc/ai_integration/AI_ASSISTANT.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AiSurface = Literal["template_editor", "workflow_editor", "run_viewer", "inventory"]

MAX_STORED_MESSAGES = 50
MAX_MESSAGE_CHARS = 20000
MAX_CONVERSATION_CHARS = 200_000
MAX_CONVERSATIONS_PER_USER = 100


class StoredToolChip(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=128)
    name: str = Field(max_length=64)
    status: Literal["running", "done", "error"] = "done"
    truncated: bool = False
    withheld: list[str] = Field(default_factory=list, max_length=10)


class StoredProposal(BaseModel):
    """What is kept of a proposal: its kind and summary, never the content or canvas."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["template", "workflow"]
    summary: str = Field(default="", max_length=2000)


class StoredMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    error: str | None = Field(default=None, max_length=2000)
    tools: list[StoredToolChip] = Field(default_factory=list, max_length=30)
    proposal: StoredProposal | None = None


class AiConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surface: AiSurface
    subject_key: str = Field(default="", max_length=64)
    # Defaults to the first user message when omitted.
    title: str | None = Field(default=None, max_length=200)
    messages: list[StoredMessage] = Field(min_length=1, max_length=MAX_STORED_MESSAGES)


class AiConversationUpdate(BaseModel):
    """Replace the messages (a later save of the same chat) and/or rename it."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    messages: list[StoredMessage] | None = Field(
        default=None, min_length=1, max_length=MAX_STORED_MESSAGES
    )


class AiConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    surface: AiSurface
    subject_key: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class AiConversationDetail(AiConversationSummary):
    messages: list[StoredMessage]
