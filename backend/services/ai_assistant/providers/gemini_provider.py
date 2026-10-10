"""Google Gemini adapter (Gemini API ``generateContent``, stateless, streaming over SSE).

The documented-and-supported ``generateContent`` API is used rather than the newer Interactions
API: the tool loop re-sends the whole conversation each step, which is exactly its model.
Function-calling turns echo the model's own ``parts`` back unchanged (they carry thought
signatures, whose absence the API rejects as ``MISSING_THOUGHT_SIGNATURE``).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from services.ai_assistant.providers.base import (
    ChatMessage,
    ProviderError,
    ProviderRefusalError,
    ProviderRequestError,
    StreamEvent,
    ToolCall,
    ToolSpec,
)
from services.ai_assistant.providers.http_common import (
    new_client,
    open_stream,
    sse_data,
    unavailable,
)

logger = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
_MODEL_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")
# Prefix for ids we invent when Gemini returns a function call without one.
GENERATED_ID_PREFIX = "gemini-call-"

_REFUSAL_REASONS = frozenset(
    {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "IMAGE_SAFETY"}
)
_BROKEN_CALL_REASONS = frozenset(
    {
        "MALFORMED_FUNCTION_CALL",
        "UNEXPECTED_TOOL_CALL",
        "TOO_MANY_TOOL_CALLS",
        "MISSING_THOUGHT_SIGNATURE",
        "MALFORMED_RESPONSE",
    }
)


def _function_responses(message: ChatMessage, names_by_id: dict[str, str]) -> dict[str, Any]:
    parts: list[dict[str, Any]] = []
    for result in message.tool_results:
        response: dict[str, Any] = {
            "name": names_by_id.get(result.tool_use_id, "unknown"),
            "response": {"error": result.content}
            if result.is_error
            else {"result": result.content},
        }
        if not result.tool_use_id.startswith(GENERATED_ID_PREFIX):
            response["id"] = result.tool_use_id
        parts.append({"functionResponse": response})
    return {"role": "user", "parts": parts}


def _to_contents(messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    names_by_id: dict[str, str] = {}
    for message in messages:
        if message.role == "assistant":
            for call in message.tool_calls:
                names_by_id[call.id] = call.name
            if message.raw is not None:
                contents.append(message.raw)
                continue
            parts: list[dict[str, Any]] = []
            if message.content:
                parts.append({"text": message.content})
            parts.extend(
                {"functionCall": {"name": call.name, "args": call.input}}
                for call in message.tool_calls
            )
            contents.append({"role": "model", "parts": parts})
        elif message.tool_results:
            contents.append(_function_responses(message, names_by_id))
        else:
            contents.append({"role": "user", "parts": [{"text": message.content}]})
    return contents


def _to_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "functionDeclarations": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parametersJsonSchema": tool.input_schema,
                }
                for tool in tools
            ]
        }
    ]


class GeminiProvider:
    def __init__(self, api_key: str, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._api_key = api_key
        self._client = http_client or new_client()

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[ChatMessage],
        max_tokens: int,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[StreamEvent]:
        if not _MODEL_ID.fullmatch(model):
            raise ProviderRequestError("The model id is not valid")
        body: dict[str, Any] = {
            "contents": _to_contents(messages),
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if tools:
            body["tools"] = _to_tools(tools)

        parts: list[dict[str, Any]] = []
        calls: list[ToolCall] = []
        finish = ""
        blocked = False
        usage: dict[str, Any] = {}

        try:
            async with open_stream(
                self._client,
                f"{API_BASE}/models/{model}:streamGenerateContent",
                params={"alt": "sse"},
                json_body=body,
                headers={"x-goog-api-key": self._api_key},
            ) as response:
                async for data in sse_data(response):
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        logger.debug("Skipping a malformed SSE chunk")
                        continue
                    if (chunk.get("promptFeedback") or {}).get("blockReason"):
                        blocked = True
                    usage = chunk.get("usageMetadata") or usage
                    for candidate in (chunk.get("candidates") or [])[:1]:
                        finish = candidate.get("finishReason") or finish
                        for part in (candidate.get("content") or {}).get("parts") or []:
                            parts.append(part)
                            if part.get("thought"):
                                continue
                            if part.get("text"):
                                yield StreamEvent(type="text", text=part["text"])
                            function_call = part.get("functionCall")
                            if function_call:
                                calls.append(
                                    ToolCall(
                                        id=function_call.get("id")
                                        or f"{GENERATED_ID_PREFIX}{len(calls) + 1}",
                                        name=function_call.get("name", ""),
                                        input=dict(function_call.get("args") or {}),
                                    )
                                )
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            logger.warning("Gemini request failed: %s", type(exc).__name__)
            raise unavailable(exc) from exc

        if blocked or finish in _REFUSAL_REASONS:
            raise ProviderRefusalError("The provider declined to answer this request")
        if finish in _BROKEN_CALL_REASONS:
            raise ProviderRequestError("The provider could not complete the tool call")
        stop_reason = "max_tokens" if finish == "MAX_TOKENS" else "end_turn"
        if calls:
            stop_reason = "tool_use" if finish != "MAX_TOKENS" else "max_tokens"
        yield StreamEvent(
            type="turn",
            tool_calls=tuple(calls),
            stop_reason=stop_reason,
            raw={"role": "model", "parts": parts},
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0)
            + int(usage.get("thoughtsTokenCount") or 0),
        )
