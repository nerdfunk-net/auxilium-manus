"""Turn a route's ``values`` (list or comma-separated string) into literals and expressions.

Shared by the route-on-attribute executor and the save-time workflow validation, so a bad
expression is reported when the workflow is saved with the same message the run would give.
"""

from __future__ import annotations

import re
from typing import Any

from services.workflow_context.attribute_expression.parser import (
    Expr,
    is_expression,
    parse_expression,
    split_values,
)

# The four former match tokens, now functions of the expression language. A bare token is
# rejected with a hint instead of silently becoming a literal that never matches.
LEGACY_TOKENS = {
    "{absent}": "{:isAbsent()}",
    "{null}": "{:isNull()}",
    "{empty}": "{:isEmpty()}",
    "{exists}": "{:exists()}",
}


# Outcome names the engine itself gives a meaning: a route called "failure" would be read as a
# device failure by every downstream wire (C6-06).
RESERVED_OUTCOMES = frozenset({"success", "failure"})


def outcome_problem(outcome: str, seen: set[str]) -> str | None:
    """Why a route outcome name is unusable, as text that follows "outcome ", or ``None``.

    ``seen`` holds the names of the routes before this one. The executor and the save-time
    validation both call this, so a workflow that saves cleanly cannot fail on its names.
    """
    if not outcome:
        return "is required"
    if outcome in RESERVED_OUTCOMES:
        return f"{outcome!r} is reserved"
    if outcome in seen:
        return f"{outcome!r} is used twice"
    return None


def raw_values_to_list(raw_values: Any) -> list[str]:
    """Normalise ``values`` (None, comma-separated string or list); ``ValueError`` otherwise."""
    if raw_values is None:
        return []
    if isinstance(raw_values, str):
        return split_values(raw_values)
    if isinstance(raw_values, list):
        return [str(item).strip() for item in raw_values if str(item).strip()]
    raise ValueError("values must be a list")


def classify_values(values: list[str]) -> tuple[list[str], list[Expr]]:
    """Split values into plain literals and parsed expressions; ``ValueError`` on a bad one."""
    literals: list[str] = []
    expressions: list[Expr] = []
    for value in values:
        replacement = LEGACY_TOKENS.get(re.sub(r"\s+", "", value.lower()))
        if replacement is not None:
            raise ValueError(f"{value!r} was replaced by {replacement!r}")
        if is_expression(value):
            expressions.append(parse_expression(value))
        else:
            literals.append(value)
    return literals, expressions
