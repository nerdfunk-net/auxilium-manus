"""Tool plumbing: a registry the agent loop calls, with one choke point for input validation,
error containment, output redaction and size capping.

Rule for every tool (doc/ai_integration/AI_ASSISTANT.md §3.5): it is either a pure read or a
proposal. Nothing here persists, executes a workflow or touches a device.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall, ToolSpec
from services.ai_assistant.redaction import Redactor

logger = logging.getLogger(__name__)

MAX_TOOL_OUTPUT_CHARS = 20000
# Matches the marker our own gating code emits; used only to tell the user what is withheld.
_NOT_SHARED = re.compile(r'"not_shared":\s*"([a-z_]+)"')


def inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``$ref`` into the definitions in place and drop ``$defs``.

    Pydantic emits ``$defs`` for nested models. Not every provider (nor every small local model)
    handles references well, so tool input schemas are sent fully inlined. Recursive models are not
    used for tool inputs; a self-reference would raise rather than loop forever.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any, stack: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name in stack:
                    raise ValueError(f"recursive tool input schema: {name}")
                merged = {k: v for k, v in node.items() if k != "$ref"}
                return resolve({**defs[name], **merged}, (*stack, name))
            return {k: resolve(v, stack) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(item, stack) for item in node]
        return node

    return resolve(schema, ())


@dataclass(frozen=True)
class ToolOutput:
    """``content`` goes back to the model. ``proposal`` (if any) goes to the client only."""

    content: str
    is_error: bool = False
    proposal: dict[str, Any] | None = None
    # The result was cut (by the tool or by the choke point); shown to the user as a hint.
    truncated: bool = False
    # Data classes the user has not opted in to that this result had to leave out.
    withheld: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolContext:
    """Request-scoped state every tool may use. Built per chat request, never shared."""

    user_id: int
    redactor: Redactor
    extras: dict[str, Any] = field(default_factory=dict)
    sharing: SharingPolicy = field(default_factory=SharingPolicy)


ToolHandler = Callable[[ToolContext, Any], Awaitable[ToolOutput]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: ToolHandler

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=inline_schema_refs(self.input_model.model_json_schema()),
        )


class Toolbox:
    def __init__(self, tools: Iterable[Tool], context: ToolContext) -> None:
        self._tools = {tool.name: tool for tool in tools}
        self._context = context

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    async def execute(self, call: ToolCall) -> ToolOutput:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolOutput(f"Unknown tool: {call.name}", is_error=True)
        try:
            args = tool.input_model.model_validate(call.input)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'input'}: {err['msg']}"
                for err in exc.errors()
            )
            return ToolOutput(f"Invalid input for {call.name}: {problems}", is_error=True)
        try:
            output = await tool.handler(self._context, args)
        except Exception:
            # Never surface internals to the model or the client; the stack goes to the log.
            logger.exception("AI assistant tool %s failed", call.name)
            return ToolOutput(f"The {call.name} tool failed unexpectedly", is_error=True)
        return self._finish(output)

    def _finish(self, output: ToolOutput) -> ToolOutput:
        content = self._context.redactor.redact(output.content)
        withheld = tuple(sorted(set(_NOT_SHARED.findall(content))))
        truncated = output.truncated
        if len(content) > MAX_TOOL_OUTPUT_CHARS:
            content = _truncate(content)
            truncated = True
        return ToolOutput(
            content=content,
            is_error=output.is_error,
            proposal=output.proposal,
            truncated=truncated,
            withheld=withheld,
        )


def _truncate(content: str) -> str:
    """Cut at a line boundary and say so, with sizes, so the model does not read a half line as
    data and knows its answer rests on partial output."""
    cut = content[:MAX_TOOL_OUTPUT_CHARS]
    newline = cut.rfind("\n")
    if newline > MAX_TOOL_OUTPUT_CHARS // 2:
        cut = cut[:newline]
    return (
        f"{cut}\n…[output truncated: showed {len(cut)} of {len(content)} characters; "
        "tell the user the answer is based on partial data]"
    )
