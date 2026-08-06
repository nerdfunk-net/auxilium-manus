"""Resolve/validate a run's static-attribute inputs before dispatch.

Shared by the manual trigger path (``RunService.trigger_run``) and the
scheduled trigger path (``hatchet.workflows.scheduled_trigger.dispatch``) so
the two never drift on what counts as a valid ``run_inputs`` payload. Pure
and DB-independent — safe to import from a FastAPI request handler or a
Hatchet task.
"""

from __future__ import annotations

from typing import Any

from models.workflows import StaticAttributeDef


class RunInputValidationError(ValueError):
    """A supplied/declared run_inputs payload doesn't satisfy the workflow's
    static_attributes schema (unknown key, missing required value, or a
    value that doesn't match its declared type)."""


def resolve_run_inputs(
    static_attributes: list[dict[str, Any]] | None,
    supplied: dict[str, Any],
) -> dict[str, Any]:
    """Merge ``supplied`` values with declared defaults and return the final
    dict to persist on ``WorkflowRun.run_inputs``.

    Raises ``RunInputValidationError`` (message names every offending field)
    when ``supplied`` contains a key not declared in ``static_attributes``,
    a declared attribute is ``required`` with no default and no supplied
    value, or a supplied/default value doesn't coerce to its declared type.
    """
    defs = [StaticAttributeDef.model_validate(raw) for raw in static_attributes or []]
    declared_names = {attr.name for attr in defs}

    unknown = sorted(set(supplied) - declared_names)
    if unknown:
        raise RunInputValidationError(
            f"Unknown run input(s) not declared on this workflow: {', '.join(unknown)}"
        )

    resolved: dict[str, Any] = {}
    errors: list[str] = []
    for attr in defs:
        if attr.name in supplied:
            resolved[attr.name] = _coerce(attr, supplied[attr.name], errors)
        elif attr.default is not None:
            resolved[attr.name] = attr.default
        elif attr.required:
            errors.append(f"{attr.name}: required, no value supplied and no default")

    if errors:
        raise RunInputValidationError("; ".join(errors))
    return resolved


def _coerce(attr: StaticAttributeDef, value: Any, errors: list[str]) -> Any:
    if attr.type == "string":
        if isinstance(value, str):
            return value
        errors.append(f"{attr.name}: expected a string")
        return None
    if attr.type == "number":
        if isinstance(value, bool):
            errors.append(f"{attr.name}: expected a number")
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value) if any(c in value for c in ".eE") else int(value)
            except ValueError:
                pass
        errors.append(f"{attr.name}: expected a number")
        return None
    if attr.type == "boolean":
        if isinstance(value, bool):
            return value
        errors.append(f"{attr.name}: expected a boolean")
        return None
    errors.append(f"{attr.name}: unsupported type {attr.type!r}")
    return None
