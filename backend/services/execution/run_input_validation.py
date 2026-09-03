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
    if attr.type == "reference":
        return _coerce_reference(attr, value, errors)
    errors.append(f"{attr.name}: unsupported type {attr.type!r}")
    return None


def _coerce_reference(attr: StaticAttributeDef, value: Any, errors: list[str]) -> Any:
    """Shape-only check for a ``type == "reference"`` value. Existence and
    per-user access are verified separately at schedule-save / dispatch time by
    services/execution/reference_resolver.py (which needs a DB session and the
    acting user); this only guarantees the payload is the right shape.

    - ``ref_kind == "inventory"`` → a positive int (an int-like str is coerced).
    - ``ref_kind == "credential"`` → a non-empty str (a credential vault name).
    """
    if attr.ref_kind == "inventory":
        if isinstance(value, bool):
            errors.append(f"{attr.name}: expected an inventory id")
            return None
        if isinstance(value, int):
            candidate = value
        elif isinstance(value, str):
            try:
                candidate = int(value)
            except ValueError:
                errors.append(f"{attr.name}: expected an inventory id")
                return None
        else:
            errors.append(f"{attr.name}: expected an inventory id")
            return None
        if candidate <= 0:
            errors.append(f"{attr.name}: expected a positive inventory id")
            return None
        return candidate
    if attr.ref_kind == "credential":
        if isinstance(value, str) and value.strip():
            return value.strip()
        errors.append(f"{attr.name}: expected a credential name")
        return None
    errors.append(f"{attr.name}: unsupported ref_kind {attr.ref_kind!r}")
    return None
