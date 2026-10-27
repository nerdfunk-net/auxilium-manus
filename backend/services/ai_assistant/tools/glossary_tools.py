"""``get_glossary``: the administrators' definitions of local words, one tool per surface.

Inventory assistant: a word ("core", "DC") -> a filter fragment. Workflow assistant: a word
("Get from GIT") -> one registry step. A pure read either way. The entries are data in the tool
result, never prompt text, and the lookup is by whole word, so a large glossary is never dumped.
An entry is re-checked on every read (against Nautobot, or against the step registry): one that
no longer holds comes back as ``stale`` WITHOUT its payload, so there is nothing for the model
to copy.
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.ai_assistant.data_sharing import DataClass, not_shared_marker
from services.ai_assistant.glossary_kinds import fold
from services.ai_assistant.inventory_filter import (
    VALUE_LIST_FIELDS,
    FilterInput,
    canonicalize_values,
    conditions_of,
    field_data_class,
)
from services.ai_assistant.tools.base import Tool, ToolContext, ToolOutput
from services.ai_assistant.tools.inventory_tools import (
    _NO_ACCESS,
    InventoryAccessError,
    _cap,
    _json,
    _state,
)


class GlossaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str = Field(
        min_length=1, max_length=64, description="The word or acronym the user used, e.g. 'core'"
    )


def _one_line(filter_: dict[str, Any]) -> dict[str, Any]:
    """Values flattened to one line with angle brackets escaped, whatever was stored."""

    def clean(condition: dict[str, Any]) -> dict[str, Any]:
        value = " ".join(str(condition["value"]).split())
        return {**condition, "value": value.replace("<", "&lt;").replace(">", "&gt;")}

    return {
        **filter_,
        "conditions": [clean(c) for c in filter_.get("conditions", [])],
        "groups": [
            {**g, "conditions": [clean(c) for c in g.get("conditions", [])]}
            for g in filter_.get("groups", [])
        ],
    }


def _unshared_class(ctx: ToolContext, filter_: FilterInput) -> DataClass | None:
    for condition in conditions_of(filter_):
        data_class = field_data_class(condition.field)
        if not ctx.sharing.allows(data_class):
            return data_class
    return None


_DID_YOU_MEAN = (
    "No entry has exactly this word. did_you_mean lists names that look similar: if one is what "
    "the user meant, call get_glossary again with that exact name; otherwise ask the user. "
    "A name in that list is not a definition."
)


async def _suggest(reader: Any, term: str) -> list[str]:
    """Close names, or none when the reader cannot suggest (never an error for the model)."""
    suggest = getattr(reader, "glossary_suggest", None) or getattr(reader, "suggest", None)
    return list(await suggest(term)) if suggest is not None else []


async def _get_glossary(ctx: ToolContext, args: GlossaryInput) -> ToolOutput:
    if not ctx.sharing.allows(DataClass.INVENTORY):
        return ToolOutput(_json(not_shared_marker(DataClass.INVENTORY)))
    reader = _state(ctx).reader
    try:
        entries = await reader.glossary_lookup(args.term)
    except InventoryAccessError:
        return _NO_ACCESS
    known: dict[str, list[dict[str, str]]] = {}
    found: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    for entry in entries:
        try:
            filter_ = FilterInput.model_validate(entry["payload"])
        except ValidationError:
            found.append({"term": entry["term"], "stale": True, "problems": ["invalid filter"]})
            continue
        blocked = _unshared_class(ctx, filter_)
        if blocked is not None:
            withheld.append({"term": entry["term"], **not_shared_marker(blocked)})
            continue
        try:
            for field in {c.field for c in conditions_of(filter_)} & set(VALUE_LIST_FIELDS):
                if field not in known:
                    known[field] = await reader.field_values(field)
        except InventoryAccessError:
            return _NO_ACCESS
        problems = [
            f"The {field} values could not be checked (Nautobot returned no names)."
            for field in sorted({c.field for c in conditions_of(filter_)} & set(VALUE_LIST_FIELDS))
            if not known.get(field)
        ]
        fixed, mismatches = canonicalize_values(filter_, known, show_names=False)
        problems.extend(mismatches)
        item: dict[str, Any] = {"term": entry["term"], "aliases": entry["aliases"]}
        if problems:
            item.update(stale=True, problems=problems)  # no filter: nothing to copy
        else:
            item["filter"] = _one_line(fixed.model_dump(mode="json"))
        found.append(item)
    result: dict[str, Any] = {"term": args.term, "entries": found}
    if withheld:
        result["withheld"] = withheld
    if not found and not withheld:
        suggestions = await _suggest(reader, args.term)
        if suggestions:
            result["did_you_mean"] = suggestions
            result["note"] = _DID_YOU_MEAN
        else:
            result["note"] = (
                "No glossary entry matches. Ask the user which Nautobot name they mean."
            )
    elif any(item.get("stale") for item in found):
        result["note"] = (
            "A stale entry names a value Nautobot no longer has: do not use its filter as is; "
            "check list_field_values and ask the user. No filter is given for it."
        )
    return ToolOutput(_json(_cap(ctx.redactor.redact_data(result))))


GLOSSARY_TOOLS: tuple[Tool, ...] = (
    Tool(
        "get_glossary",
        "Look up a word or acronym the user used that matches no Nautobot name (for example "
        "'core' or 'DC'). Returns the administrators' definition as a filter fragment to combine "
        "with the user's other conditions in preview_filter / propose_inventory. The match is on "
        "the whole word or phrase, so if nothing matches, follow did_you_mean.",
        GlossaryInput,
        _get_glossary,
    ),
)


# -- workflow assistant: step aliases --------------------------------------------------------------


class StepAliasLookup(Protocol):
    async def lookup(self, term: str) -> list[dict[str, Any]]: ...

    async def suggest(self, term: str) -> list[str]: ...


def _live_step_names(registry: Any) -> dict[str, str]:
    """Folded id and display name of every enabled, executable step -> its id (ids win)."""
    steps = [p for p in registry.list_plugins() if p.executable]
    return {fold(p.name): p.id for p in steps} | {fold(p.id): p.id for p in steps}


async def _get_step_alias(ctx: ToolContext, args: GlossaryInput) -> ToolOutput:
    state = ctx.extras["workflow_editor"]
    lookup: StepAliasLookup = ctx.extras["glossary"]
    live = _live_step_names(state.registry)
    found: list[dict[str, Any]] = []
    for entry in await lookup.lookup(args.term):
        step_id = entry["payload"].get("step_id")
        plugin = state.registry.get_plugin(step_id) if isinstance(step_id, str) else None
        item: dict[str, Any] = {"term": entry["term"], "aliases": entry["aliases"]}
        # A step added or enabled after the alias was saved may now own the word.
        shadowed = next(
            ((n, live[fold(n)]) for n in (entry["term"], *entry["aliases"]) if fold(n) in live),
            None,
        )
        if shadowed is not None:
            item.update(
                stale=True,
                problems=[f"'{shadowed[0]}' is now the id or display name of step {shadowed[1]}."],
            )
        elif plugin is None or not plugin.executable:
            item.update(stale=True, problems=["The step no longer exists or is disabled."])
        else:
            # Taken fresh from the registry: nothing the administrator typed besides the word.
            item["step"] = {"id": plugin.id, "name": plugin.name, "overview": plugin.overview}
        found.append(item)
    result: dict[str, Any] = {"term": args.term, "entries": found}
    if not found:
        suggestions = await _suggest(lookup, args.term)
        if suggestions:
            result["did_you_mean"] = suggestions
            result["note"] = _DID_YOU_MEAN
        else:
            result["note"] = (
                "No alias for this word. Use list_steps, or ask the user which step they mean."
            )
    elif any(item.get("stale") for item in found):
        result["note"] = (
            "A stale alias points to a step that is gone, or its word is now a real step's "
            "name: do not use it; use list_steps or ask the user."
        )
    else:
        result["note"] = "Call get_step_schema for the step before configuring it."
    return ToolOutput(_json(_cap(ctx.redactor.redact_data(result))))


STEP_ALIAS_TOOLS: tuple[Tool, ...] = (
    Tool(
        "get_glossary",
        "Look up a word the user used for a workflow step that matches no step id or name in "
        "list_steps (a nickname or local term, for example 'Get from GIT'). Returns the "
        "administrators' alias: the step it means. Pass the shortest phrase the user used for the "
        "step; the match is on the whole phrase, so if nothing matches, follow did_you_mean.",
        GlossaryInput,
        _get_step_alias,
    ),
)
