"""``get_glossary``: the administrators' definitions of local words ("core", "DC") as filters.

A pure read. The entries are data in the tool result, never prompt text, and the lookup is by
word, so a large glossary is never dumped. An entry is re-checked against Nautobot on every read:
a value that was renamed since the entry was saved comes back as ``stale`` instead of as a filter
that would match nothing.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from services.ai_assistant.data_sharing import DataClass, not_shared_marker
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
            filter_ = FilterInput.model_validate(entry["filter"])
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
        result["note"] = "No glossary entry matches. Ask the user which Nautobot name they mean."
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
        "with the user's other conditions in preview_filter / propose_inventory.",
        GlossaryInput,
        _get_glossary,
    ),
)
