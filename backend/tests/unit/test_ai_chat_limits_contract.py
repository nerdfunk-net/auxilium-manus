"""The chat history builder in the frontend and the request limits in the backend agree (C14)."""

from __future__ import annotations

import re
from pathlib import Path

from models.ai_assistant import ChatMessageIn, ChatRequest

TS = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "components"
    / "features"
    / "ai-assistant"
    / "utils"
    / "chat-history.ts"
)


def _ts_limit(name: str) -> int:
    match = re.search(rf"{name}:\s*([0-9_]+)", TS.read_text(encoding="utf-8"))
    assert match, f"{name} not found in chat-history.ts"
    return int(match.group(1).replace("_", ""))


def _max_length(model: type, field: str, constraint: str) -> int:
    for item in model.model_fields[field].metadata:
        value = getattr(item, constraint, None)
        if value is not None:
            return int(value)
    raise AssertionError(f"{model.__name__}.{field} has no {constraint}")


def test_max_messages_matches_the_request_model() -> None:
    assert _ts_limit("maxMessages") == _max_length(ChatRequest, "messages", "max_length")


def test_max_message_chars_matches_the_message_model() -> None:
    assert _ts_limit("maxMessageChars") == _max_length(ChatMessageIn, "content", "max_length")
