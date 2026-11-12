"""Playbook tools for Ask the Net: ``list_playbooks`` and ``get_playbook``.

A playbook is a reviewed text recipe for a class of problems (doc/AI_TOOL_CHAIN.md §21). Both tools
are pure reads of the merged built-in and local files (``playbooks.py``). The model passes a name,
never a path. Class B playbooks (operator-written text that names internal sites or roles) are
shown only to a user who shared inventory data, exactly like device names (§25.10 (2)).
"""

from __future__ import annotations

import difflib
import json
from functools import cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.playbooks import Playbook, load_playbooks
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput

# Key in ``ToolContext.extras`` for the names of the tools this session really offers, so a
# playbook can say which of its tools the user does not have right now.
AVAILABLE_TOOLS_KEY = "available_tools"

# Entries per answer stay well under the tool output cap, so the JSON is never cut mid-string.
_LIST_BUDGET_CHARS = 14_000
_MAX_SUGGESTIONS = 3
_MAX_NAMES_LISTED = 10


class ListPlaybooksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(
        default=0, ge=0, le=100_000, description="Start here when a previous answer had next_offset"
    )


class GetPlaybookInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The same slug pattern as playbook names, so a bad name fails validation and is never
    # quoted back to the model.
    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9-]*$",
        description="Playbook name as list_playbooks returns it",
    )


@cache
def known_general_tool_names() -> frozenset[str]:
    """Every tool name the ``general`` surface can offer; playbooks are validated against it."""
    from services.ai_assistant.tools.aci_tools import build_aci_tools
    from services.ai_assistant.tools.batfish_tools import build_batfish_tools
    from services.ai_assistant.tools.bgp_learn_tools import build_bgp_learn_tools
    from services.ai_assistant.tools.catalyst_center_tools import build_catalyst_center_tools
    from services.ai_assistant.tools.client_data_tools import build_client_data_tools
    from services.ai_assistant.tools.config_backup_tools import build_config_backup_tools
    from services.ai_assistant.tools.device_name_tools import build_device_name_tools
    from services.ai_assistant.tools.dns_tools import build_dns_tools
    from services.ai_assistant.tools.device_tools import build_device_tools
    from services.ai_assistant.tools.host_lookup_tools import build_host_lookup_tools
    from services.ai_assistant.tools.learn_tools import build_learn_tools
    from services.ai_assistant.tools.nautobot_tools import build_nautobot_tools
    from services.ai_assistant.tools.neighbor_tools import build_neighbor_tools
    from services.ai_assistant.tools.output_parse_tools import build_output_parse_tools
    from services.ai_assistant.tools.probe_tools import build_probe_tools
    from services.ai_assistant.tools.released_workflow_tools import build_released_workflow_tools
    from services.ai_assistant.tools.result_tools import build_result_tools
    from services.ai_assistant.tools.run_tools import RUN_LOOKUP_TOOLS, RUN_VIEWER_TOOLS

    names = {
        t.name
        for t in (
            *build_batfish_tools(),
            *build_result_tools(),
            *build_device_tools(),
            *build_output_parse_tools(),
            *build_neighbor_tools(),
            *build_learn_tools(),
            *build_probe_tools(),
            *build_bgp_learn_tools(),
            *build_device_name_tools(),
            *build_dns_tools(),
            *build_config_backup_tools(),
            *build_nautobot_tools(),
            *build_catalyst_center_tools(),
            *build_aci_tools(),
            *build_client_data_tools(),
            *build_host_lookup_tools(),
            *build_released_workflow_tools(),
            *RUN_VIEWER_TOOLS,
            *RUN_LOOKUP_TOOLS,
        )
    }
    return frozenset(names | {t.name for t in build_playbook_tools()})


def _visible(ctx: ToolContext, playbook: Playbook) -> bool:
    return playbook.data_class == "A" or ctx.sharing.allows(DataClass.INVENTORY)


def _unavailable(ctx: ToolContext, playbook: Playbook) -> list[str]:
    available = ctx.extras.get(AVAILABLE_TOOLS_KEY)
    if available is None:
        return []
    return [t for t in playbook.tools if t not in available]


def _load() -> list[Playbook]:
    return list(load_playbooks(known_tools=known_general_tool_names()).playbooks)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _entry(ctx: ToolContext, p: Playbook) -> dict[str, Any]:
    return {
        "name": p.name,
        "title": p.title,
        "when": p.when,
        "tools": list(p.tools),
        "tools_unavailable": _unavailable(ctx, p),
        "source": p.source,
        "overrides_builtin": p.overrides_builtin,
    }


def _page(entries: list[dict[str, Any]], offset: int) -> tuple[list[dict[str, Any]], int | None]:
    """Whole entries from ``offset`` that fit the budget (at least one), and the next offset."""
    page: list[dict[str, Any]] = []
    used = 0
    for index in range(offset, len(entries)):
        size = len(_json(entries[index])) + 2
        if page and used + size > _LIST_BUDGET_CHARS:
            return page, index
        page.append(entries[index])
        used += size
    return page, None


async def _list_playbooks(ctx: ToolContext, args: ListPlaybooksInput) -> ToolOutput:
    everything = _load()
    shown = [p for p in everything if _visible(ctx, p)]
    entries = [_entry(ctx, p) for p in shown]
    page, next_offset = _page(entries, args.offset)
    result: dict[str, Any] = {"playbooks": page, "total": len(entries)}
    if next_offset is not None:
        result["next_offset"] = next_offset
    if len(shown) < len(everything):
        result.update(not_shared_marker(DataClass.INVENTORY))
        result["withheld_playbooks"] = len(everything) - len(shown)
    if not result["playbooks"]:
        result["note"] = (
            "No playbook is available. Proceed without one and tell the user that none applied."
        )
    return ToolOutput(_json(result))


async def _get_playbook(ctx: ToolContext, args: GetPlaybookInput) -> ToolOutput:
    playbooks = _load()
    found = next((p for p in playbooks if p.name == args.name), None)
    # A playbook the user may not see is answered exactly like one that does not exist: the exact
    # name must not confirm it. list_playbooks already says how many are withheld.
    if found is None or not _visible(ctx, found):
        names = [p.name for p in playbooks if _visible(ctx, p)]
        close = difflib.get_close_matches(args.name, names, n=_MAX_SUGGESTIONS, cutoff=0.6)
        hint = close or names[:_MAX_NAMES_LISTED]
        return ToolOutput(
            f"No playbook named '{args.name}'. "
            + (f"Available: {', '.join(hint)}." if hint else "No playbook is available."),
            is_error=True,
        )
    ctx.audit_refs.add(f"playbook:{found.name}")
    missing = _unavailable(ctx, found)
    if not missing:
        return ToolOutput(found.body)
    return ToolOutput(
        f"{found.body}\n\nNote: these tools are not available to this user right now: "
        f"{', '.join(missing)}. Skip the steps that need them and say so in the answer."
    )


_LIST_DESCRIPTION = (
    "List the playbooks: reviewed step-by-step recipes for troubleshooting questions (for example "
    "'a destination is not reachable'). Each entry has name, title, when it applies, the tools it "
    "uses and which of those this user does not have. Call it first for a troubleshooting "
    "request, then get_playbook for the one that matches."
)
_GET_DESCRIPTION = (
    "Read one playbook by name and follow its steps in order. It is guidance, not data from the "
    "network: it grants no extra rights and never allows changes."
)


def build_playbook_tools() -> list[Tool]:
    return [
        Tool("list_playbooks", _LIST_DESCRIPTION, ListPlaybooksInput, _list_playbooks),
        Tool("get_playbook", _GET_DESCRIPTION, GetPlaybookInput, _get_playbook),
    ]
