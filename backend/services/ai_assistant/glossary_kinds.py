"""What each glossary kind validates when an administrator saves an entry.

``inventory_filter``: structure, plain-text values and Nautobot names (respelled as Nautobot spells
them). ``workflow_step``: the step must exist in the registry, be enabled and executable, and an
alias may not shadow a real step id or display name. Nothing here is free text for the model; the
read-time re-checks live in the tools (``tools/glossary_tools.py``).
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from core.domain_exceptions import ConflictError, ValidationFailedError
from models.ai_glossary import InventoryTermBody, StepAliasBody
from models.plugins import PluginDefinition
from services.ai_assistant.inventory_filter import (
    VALUE_LIST_FIELDS,
    FilterInput,
    canonicalize_values,
    conditions_of,
    structure_errors,
)
from services.ai_assistant.tools.inventory_tools import InventoryAccessError

logger = logging.getLogger(__name__)

# Values reach the model as the administrators' definition, so they stay plain one-line text.
_FORBIDDEN_VALUE_CHARS = re.compile(r"[<>\x00-\x1f\x7f]")
MAX_CLOSE_MATCHES = 3


def fold(name: str) -> str:
    """The form a term or alias is compared in: collapsed whitespace, lower case."""
    return " ".join(name.split()).lower()


class FieldValueReader(Protocol):
    async def field_values(self, field: str) -> list[dict[str, str]]: ...


class StepCatalogue(Protocol):
    def list_plugins(self, include_disabled: bool = False) -> list[PluginDefinition]: ...

    def get_plugin(
        self, plugin_id: str, include_disabled: bool = False
    ) -> PluginDefinition | None: ...


@dataclass(frozen=True)
class SaveContext:
    """What a save may need: Nautobot names for inventory entries, the registry for step aliases."""

    fields: FieldValueReader | None = None
    registry: StepCatalogue | None = None


async def prepare_payload(
    body: InventoryTermBody | StepAliasBody, context: SaveContext
) -> dict[str, Any]:
    """Validate ``body`` and return the payload to store."""
    if isinstance(body, InventoryTermBody):
        if context.fields is None:
            raise ValidationFailedError("No Nautobot source is available to check the values")
        return (await _prepare_filter(body.filter, context.fields)).model_dump(mode="json")
    if context.registry is None:
        raise ValidationFailedError("The step registry is unavailable")
    return _prepare_step_alias(body, context.registry)


# -- workflow_step -------------------------------------------------------------------------------


def _prepare_step_alias(body: StepAliasBody, registry: StepCatalogue) -> dict[str, Any]:
    steps = [p for p in registry.list_plugins() if p.executable]
    plugin = next((p for p in steps if p.id == body.step_id), None)
    if plugin is None:
        close = difflib.get_close_matches(
            body.step_id, [p.id for p in steps], n=MAX_CLOSE_MATCHES, cutoff=0.5
        )
        hint = f" Closest: {', '.join(close)}." if close else " Use a registry step id."
        raise ValidationFailedError(
            f"'{body.step_id}' is not an enabled, executable workflow step.{hint}"
        )
    # Ids win over display names, so the error names the step the word really is.
    real_names = {fold(p.name): p.id for p in steps} | {fold(p.id): p.id for p in steps}
    for name in (body.term, *body.aliases):
        owner = real_names.get(fold(name))
        if owner is not None:
            raise ConflictError(
                f"'{name}' is already the id or display name of the step '{owner}'; "
                "an alias must be a different word"
            )
    return {"step_id": plugin.id}


# -- inventory_filter ----------------------------------------------------------------------------


async def _prepare_filter(filter_: FilterInput, reader: FieldValueReader) -> FilterInput:
    """Structure checks, then values respelled as Nautobot spells them.

    A value that cannot be checked is refused: an unchecked value would be served to the model as
    the administrators' definition.
    """
    errors = structure_errors(filter_)
    errors.extend(
        f"{c.field} value {c.value!r} must be plain single-line text without < or >."
        for c in conditions_of(filter_)
        if _FORBIDDEN_VALUE_CHARS.search(c.value)
    )
    if errors:
        raise ValidationFailedError("The filter is invalid: " + " ".join(errors))
    fields = sorted({c.field for c in conditions_of(filter_) if c.field in VALUE_LIST_FIELDS})
    known: dict[str, list[dict[str, str]]] = {}
    for field in fields:
        try:
            known[field] = await reader.field_values(field)
        except InventoryAccessError as exc:
            raise ValidationFailedError(
                "Nautobot names could not be read with this source (permission or source id)"
            ) from exc
        except Exception as exc:  # Nautobot unreachable
            logger.warning("AI glossary: could not load %s values from Nautobot", field)
            raise ValidationFailedError(_unverifiable(field)) from exc
        if not known[field]:
            raise ValidationFailedError(_unverifiable(field))
    fixed, mismatches = canonicalize_values(filter_, known, show_names=True)
    if mismatches:
        raise ValidationFailedError("The filter has unknown values: " + " ".join(mismatches))
    return fixed


def _unverifiable(field: str) -> str:
    return (
        f"The {field} values could not be checked because Nautobot returned no names. "
        "Try again when the source is reachable."
    )
