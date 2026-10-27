"""The inventory filter as the model writes it, and the saved-tree shape the builder loads.

The model emits a small non-recursive structure (a root with conditions and one level of groups:
tool schemas cannot be recursive and small local models cope better with a flat one). It is
checked against the rules the inventory builder enforces, its values are matched against what
Nautobot really has, and it is turned into the version-2 condition tree the builder saves, which
``utils.inventory_converter.tree_to_operations`` evaluates. Nothing here does I/O.
"""

from __future__ import annotations

import difflib
import ipaddress
import re
import uuid
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.ai_assistant.data_sharing import DataClass

Logic = Literal["AND", "OR"]
Operator = Literal[
    "equals", "not_equals", "contains", "not_contains", "within_include", "within", "exact"
]

_EQUALS: tuple[str, ...] = ("equals",)
_EQUALS_OR_NOT: tuple[str, ...] = ("equals", "not_equals")
_TEXT: tuple[str, ...] = ("equals", "contains")
# Mirrors frontend inventory/utils/field-operators.ts: what the builder offers per field.
OPERATORS_BY_FIELD: dict[str, tuple[str, ...]] = {
    "name": _TEXT,
    "location": _EQUALS_OR_NOT,
    "role": _EQUALS_OR_NOT,
    "status": _EQUALS_OR_NOT,
    "tag": _EQUALS_OR_NOT,
    "device_type": _EQUALS_OR_NOT,
    "manufacturer": _EQUALS_OR_NOT,
    "platform": _EQUALS,
    "has_primary": _EQUALS,
    "ip_prefix": ("within_include", "within", "exact"),
    "primary_prefix": ("within_include",),
}
CUSTOM_FIELD = re.compile(r"^cf_[A-Za-z0-9_]+$")
# Fields whose value must be one of Nautobot's names (see NautobotSourceMetadataService).
VALUE_LIST_FIELDS = (
    "location",
    "role",
    "status",
    "tag",
    "device_type",
    "manufacturer",
    "platform",
)
MAX_CONDITIONS = 20
MAX_GROUPS = 10
MAX_VALUE_CHARS = 200
MAX_AVAILABLE_NAMES = 30

_DESCRIBE_MAX_DEPTH = 6
_DESCRIBE_MAX_LINES = 100


_PREFIX_FIELDS = ("ip_prefix", "primary_prefix")
_PREFIX_NAMESPACE = re.compile(r"^[A-Za-z0-9_.-]+$")


def field_data_class(field: str) -> DataClass:
    """The data class a condition on ``field`` touches. Matching on a field tells whoever sees
    the result (a count, rows) something about that class, so the class must be shared."""
    if field in _PREFIX_FIELDS:
        return DataClass.ADDRESSES
    if field.startswith("cf_"):
        return DataClass.CUSTOM_FIELDS
    return DataClass.INVENTORY


def conditions_of(filter_: FilterInput) -> list[FilterCondition]:
    return [*filter_.conditions, *(c for g in filter_.groups for c in g.conditions)]


def _bad_prefix(value: str) -> bool:
    """True unless ``value`` is ``"<cidr> [namespace]"``; the evaluator swallows bad input."""
    parts = value.strip().split(None, 1)
    if not parts:
        return True
    try:
        ipaddress.ip_network(parts[0], strict=False)
    except ValueError:
        return True
    return len(parts) > 1 and not _PREFIX_NAMESPACE.match(parts[1].strip())


def allowed_operators(field: str) -> tuple[str, ...]:
    return OPERATORS_BY_FIELD.get(field, _TEXT)  # custom fields behave like names


class FilterCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(
        min_length=1,
        max_length=64,
        description=f"One of: {', '.join(OPERATORS_BY_FIELD)}, or cf_<custom field name>",
    )
    operator: Operator
    value: str = Field(min_length=1, max_length=MAX_VALUE_CHARS)

    @field_validator("field")
    @classmethod
    def _known_field(cls, value: str) -> str:
        if value not in OPERATORS_BY_FIELD and not CUSTOM_FIELD.match(value):
            raise ValueError(
                f"unknown field {value!r}; use one of {', '.join(OPERATORS_BY_FIELD)} "
                "or cf_<custom field name>"
            )
        return value


class FilterGroup(BaseModel):
    """A bracketed set of conditions; ``negate`` excludes the devices it matches."""

    model_config = ConfigDict(extra="forbid")

    logic: Logic = "AND"
    negate: bool = False
    conditions: list[FilterCondition] = Field(min_length=1, max_length=MAX_CONDITIONS)


class FilterInput(BaseModel):
    """Root: ``conditions`` and ``groups`` are combined with ``logic``."""

    model_config = ConfigDict(extra="forbid")

    logic: Logic = "AND"
    conditions: list[FilterCondition] = Field(default_factory=list, max_length=MAX_CONDITIONS)
    groups: list[FilterGroup] = Field(default_factory=list, max_length=MAX_GROUPS)


def structure_errors(filter_: FilterInput) -> list[str]:
    """Rules the builder enforces, plus: a filter must select something."""
    errors = [
        f"{c.field} does not support the operator {c.operator!r}; use "
        f"{' or '.join(allowed_operators(c.field))}."
        for c in conditions_of(filter_)
        if c.operator not in allowed_operators(c.field)
    ]
    errors.extend(
        f"{c.field} value {c.value!r} is not a valid prefix; use CIDR, e.g. 10.0.0.0/8, "
        "optionally followed by a namespace name."
        for c in conditions_of(filter_)
        if c.field in _PREFIX_FIELDS and _bad_prefix(c.value)
    )
    if not filter_.conditions and not any(not g.negate for g in filter_.groups):
        errors.append(
            "The filter needs at least one positive condition or non-negated group: a filter "
            "made only of excluded groups matches nothing."
        )
    return errors


def _canonical_value(
    condition: FilterCondition,
    known: Sequence[Mapping[str, str]] | None,
    show_names: bool,
) -> tuple[FilterCondition, str | None]:
    if condition.field == "has_primary":
        lowered = condition.value.strip().lower()
        if lowered in ("true", "false"):
            return condition.model_copy(update={"value": lowered}), None
        return condition, "has_primary must be 'true' or 'false'."
    if condition.field not in VALUE_LIST_FIELDS or not known:
        return condition, None  # free text, or the list could not be loaded: unverified
    names = [str(item["value"]) for item in known]
    by_lower: dict[str, list[str]] = defaultdict(list)
    for name in dict.fromkeys(names):
        by_lower[name.lower()].append(name)
    spelled = condition.value.strip()
    matches = by_lower.get(spelled.lower(), [])
    if len(matches) > 1 and spelled in matches:
        return condition.model_copy(update={"value": spelled}), None  # exact spelling wins
    if len(matches) > 1:
        listing = f": {', '.join(matches)}" if show_names else ""
        return condition, (
            f"{condition.field} '{condition.value}' matches {len(matches)} Nautobot names that "
            f"differ only by case{listing}. Ask the user which one they mean and use that exact "
            "spelling."
        )
    if matches:
        return condition.model_copy(update={"value": matches[0]}), None
    message = f"{condition.field} '{condition.value}' does not exist in Nautobot."
    if show_names:
        close = difflib.get_close_matches(condition.value, names, n=3, cutoff=0.5)
        if close:
            message += f" Closest: {', '.join(close)}."
        shown = names[:MAX_AVAILABLE_NAMES]
        more = f" (+{len(names) - len(shown)} more)" if len(names) > len(shown) else ""
        message += f" Available: {', '.join(shown)}{more}."
    return condition, message


def canonicalize_values(
    filter_: FilterInput,
    known: Mapping[str, Sequence[Mapping[str, str]]],
    *,
    show_names: bool = False,
) -> tuple[FilterInput, list[str]]:
    """A copy of ``filter_`` with values spelled as Nautobot spells them, and what did not match.

    ``known`` maps a field to Nautobot's ``{"value", "label"}`` rows. ``show_names`` is False when
    the user has not shared inventory data: the error then never lists names.
    """
    errors: list[str] = []

    def fix(conditions: list[FilterCondition]) -> list[FilterCondition]:
        fixed: list[FilterCondition] = []
        for condition in conditions:
            new, error = _canonical_value(condition, known.get(condition.field), show_names)
            fixed.append(new)
            if error:
                errors.append(error)
        return fixed

    groups = [g.model_copy(update={"conditions": fix(g.conditions)}) for g in filter_.groups]
    return filter_.model_copy(
        update={"conditions": fix(filter_.conditions), "groups": groups}
    ), errors


def _node_id() -> str:
    return uuid.uuid4().hex[:12]


def _condition_item(condition: FilterCondition) -> dict[str, Any]:
    return {
        "id": _node_id(),
        "field": condition.field,
        "operator": condition.operator,
        "value": condition.value,
    }


def build_condition_tree(filter_: FilterInput) -> dict[str, Any]:
    """The version-2 ``ConditionTree`` the inventory builder saves and loads."""
    items: list[dict[str, Any]] = [_condition_item(c) for c in filter_.conditions]
    items.extend(
        {
            "id": _node_id(),
            "type": "group",
            "logic": "NOT" if group.negate else "AND",
            "internalLogic": group.logic,
            "items": [_condition_item(c) for c in group.conditions],
        }
        for group in filter_.groups
    )
    return {"type": "root", "internalLogic": filter_.logic, "items": items}


def describe_condition_tree(tree: Any, hide: Callable[[str], bool] | None = None) -> str:
    """A readable, bounded, single-line-per-condition rendering of a client-supplied (so
    untrusted) condition tree.

    It ends up inside the system prompt, so text is flattened to one line and angle brackets are
    escaped: a value cannot close the surrounding tag or start a new line of instructions.
    ``hide(field)`` is true for fields whose values the user has not shared; those show a marker.
    """
    lines: list[str] = []

    def condition(item: dict[str, Any], indent: str) -> str:
        field = _text(item.get("field"), 64)
        value = "(not shared)" if hide and hide(field) else _text(item.get("value"))
        return f"{indent}- {field} {_text(item.get('operator'), 32)} {value}"

    def walk(items: Any, depth: int) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if len(lines) >= _DESCRIBE_MAX_LINES:
                return
            if not isinstance(item, dict):
                continue
            indent = "  " * depth
            if item.get("type") == "group":
                if depth >= _DESCRIBE_MAX_DEPTH:
                    lines.append(f"{indent}(deeper groups omitted)")
                    continue
                negated = "NOT " if item.get("logic") == "NOT" else ""
                lines.append(
                    f"{indent}{negated}group, match {_text(item.get('internalLogic'), 8)}:"
                )
                walk(item.get("items"), depth + 1)
            else:
                lines.append(condition(item, indent))

    if isinstance(tree, dict):
        lines.append(f"match {_text(tree.get('internalLogic') or 'AND', 8)} of:")
        walk(tree.get("items"), 1)
    if len(lines) >= _DESCRIBE_MAX_LINES:
        lines.append("(more conditions omitted)")
    return "\n".join(lines)


def _text(value: Any, limit: int = MAX_VALUE_CHARS) -> str:
    flat = " ".join(str(value if value is not None else "").split())  # one line, no controls
    return flat[:limit].replace("<", "&lt;").replace(">", "&gt;")
