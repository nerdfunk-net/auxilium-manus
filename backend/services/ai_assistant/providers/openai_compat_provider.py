"""OpenAI-compatible adapter (``/chat/completions`` over SSE): Ollama, LM Studio, vLLM, OpenAI.

The base URL is user-configured, so it goes through the outbound-URL policy right before every
call (the same check that ran when it was saved), redirects are never followed, and an API key is
optional (local servers usually have none). Local models vary in tool-calling quality, so
malformed tool arguments are passed on as an invalid input (the tool layer rejects it and the
model can retry) instead of failing the turn.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from services.ai_assistant.base_url_policy import BaseUrlPolicyError, validate_llm_base_url_async
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

MAX_INVALID_ARGS_CHARS = 200


def _to_messages(system: str, messages: Sequence[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        if message.role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": message.content or None}
            if message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.input)},
                    }
                    for call in message.tool_calls
                ]
            out.append(entry)
        elif message.tool_results:
            out.extend(
                {"role": "tool", "tool_call_id": result.tool_use_id, "content": result.content}
                for result in message.tool_results
            )
        else:
            out.append({"role": "user", "content": message.content})
    return out


def _to_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def _parse_arguments(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return {"_invalid_json": raw[:MAX_INVALID_ARGS_CHARS]}
    return value if isinstance(value, dict) else {"_invalid_json": raw[:MAX_INVALID_ARGS_CHARS]}


class OpenAiCompatProvider:
    def __init__(
        self, base_url: str, api_key: str = "", *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owns_client = http_client is None
        self._client = http_client or new_client()

    async def aclose(self) -> None:
        # An injected client belongs to the caller.
        if self._owns_client:
            await self._client.aclose()

    async def stream(
        self,
        *,
        model: str,
        system: str,
        messages: list[ChatMessage],
        max_tokens: int,
        tools: Sequence[ToolSpec] = (),
    ) -> AsyncIterator[StreamEvent]:
        try:
            await validate_llm_base_url_async(self._base_url, has_api_key=bool(self._api_key))
        except BaseUrlPolicyError as exc:
            raise ProviderRequestError("The configured server URL is not allowed") from exc

        body: dict[str, Any] = {
            "model": model,
            "messages": _to_messages(system, messages),
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = _to_tools(tools)
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

        fragments: dict[int, dict[str, str]] = {}
        finish = ""
        usage: dict[str, Any] = {}

        try:
            async with open_stream(
                self._client,
                f"{self._base_url}/chat/completions",
                json_body=body,
                headers=headers,
            ) as response:
                async for data in sse_data(response):
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except ValueError:
                        logger.debug("Skipping a malformed SSE chunk")
                        continue
                    usage = chunk.get("usage") or usage
                    for choice in (chunk.get("choices") or [])[:1]:
                        finish = choice.get("finish_reason") or finish
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            yield StreamEvent(type="text", text=delta["content"])
                        for fragment in delta.get("tool_calls") or []:
                            slot = fragments.setdefault(
                                int(fragment.get("index", 0)), {"id": "", "name": "", "args": ""}
                            )
                            slot["id"] = fragment.get("id") or slot["id"]
                            function = fragment.get("function") or {}
                            slot["name"] = function.get("name") or slot["name"]
                            slot["args"] += function.get("arguments") or ""
        except ProviderError:
            raise
        except httpx.HTTPError as exc:
            logger.warning("OpenAI-compatible request failed: %s", type(exc).__name__)
            raise unavailable() from exc

        if finish == "content_filter":
            raise ProviderRefusalError("The provider declined to answer this request")
        calls = tuple(
            ToolCall(
                id=slot["id"] or f"call_{index + 1}",
                name=slot["name"],
                input=_parse_arguments(slot["args"]),
            )
            for index, slot in sorted(fragments.items())
            if slot["name"]
        )
        if finish == "length":
            stop_reason = "max_tokens"
        elif calls:
            stop_reason = "tool_use"
        else:
            stop_reason = "end_turn"
        yield StreamEvent(
            type="turn",
            tool_calls=calls,
            stop_reason=stop_reason,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )
