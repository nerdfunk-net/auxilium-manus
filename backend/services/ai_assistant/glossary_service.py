"""Inventory assistant glossary: admin-managed terms that expand into a small structured filter.

An entry maps a word ("core", "DC") plus aliases to a ``FilterInput``. Values are checked and
respelled against Nautobot on save (``canonicalize_values``). A save is refused while Nautobot
cannot supply the names a value must match, and values must be single-line text without angle
brackets: the model receives term, aliases and filter as data through ``get_glossary`` and is
told to apply them (doc/ai_integration/AI_ASSISTANT.md).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from sqlalchemy.orm import Session

from core.domain_exceptions import ConflictError, NotFoundError, ValidationFailedError
from core.models.ai_glossary import AiGlossaryTerm
from models.ai_glossary import (
    GlossaryListResponse,
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
)
from repositories.ai_glossary_repository import AiGlossaryRepository
from services.ai_assistant.inventory_filter import (
    VALUE_LIST_FIELDS,
    FilterInput,
    canonicalize_values,
    conditions_of,
    structure_errors,
)
from services.ai_assistant.tools.inventory_tools import InventoryAccessError

logger = logging.getLogger(__name__)

MAX_TERMS = 500
MAX_LOOKUP_RESULTS = 10
# Values reach the model as the administrators' definition, so they stay plain one-line text.
_FORBIDDEN_VALUE_CHARS = re.compile(r"[<>\x00-\x1f\x7f]")


def fold(name: str) -> str:
    """The form a term or alias is compared in: collapsed whitespace, lower case."""
    return " ".join(name.split()).lower()


class FieldValueReader(Protocol):
    async def field_values(self, field: str) -> list[dict[str, str]]: ...


def _to_response(row: AiGlossaryTerm, warnings: list[str] | None = None) -> GlossaryTermResponse:
    return GlossaryTermResponse(
        id=row.id,
        term=row.term,
        aliases=list(row.aliases or []),
        filter=dict(row.filter),
        note=row.note,
        warnings=warnings or [],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class GlossaryService:
    def __init__(self, db: Session) -> None:
        self._repo = AiGlossaryRepository(db)

    # -- admin reads ---------------------------------------------------------

    def list_terms(self, query: str | None, limit: int, offset: int) -> GlossaryListResponse:
        rows = self._repo.search(query, limit, offset)
        return GlossaryListResponse(
            items=[_to_response(r) for r in rows], total=self._repo.count(query)
        )

    # -- admin writes --------------------------------------------------------

    async def create(
        self, body: GlossaryTermCreate, reader: FieldValueReader, actor_user_id: int
    ) -> GlossaryTermResponse:
        if self._repo.count() >= MAX_TERMS:
            raise ConflictError(f"The glossary is limited to {MAX_TERMS} terms")
        self._check_names_free(body, own_id=None)
        fixed, warnings = await _prepare_filter(body.filter, reader)
        row = self._repo.create(_values(body, fixed), _names(body), created_by_id=actor_user_id)
        logger.info("AI glossary term created id=%s by user_id=%s", row.id, actor_user_id)
        return _to_response(row, warnings)

    async def update(
        self, term_id: int, body: GlossaryTermUpdate, reader: FieldValueReader, actor_user_id: int
    ) -> GlossaryTermResponse:
        row = self._repo.get(term_id)
        if row is None:
            raise NotFoundError("Glossary term not found")
        self._check_names_free(body, own_id=term_id)
        fixed, warnings = await _prepare_filter(body.filter, reader)
        row = self._repo.update(row, _values(body, fixed), _names(body))
        logger.info("AI glossary term updated id=%s by user_id=%s", row.id, actor_user_id)
        return _to_response(row, warnings)

    def delete(self, term_id: int, actor_user_id: int) -> None:
        row = self._repo.get(term_id)
        if row is None:
            raise NotFoundError("Glossary term not found")
        self._repo.delete(row)
        logger.info("AI glossary term deleted id=%s by user_id=%s", term_id, actor_user_id)

    def _check_names_free(self, body: GlossaryTermCreate | GlossaryTermUpdate, own_id: int | None):
        wanted = _names(body)
        if len(set(wanted)) != len(wanted):
            raise ValidationFailedError("A term and its aliases must all be different")
        clash = self._repo.names_in_use(wanted, own_id)
        if clash:
            raise ConflictError(f"'{clash[0]}' is already used by another glossary term")

    # -- assistant lookup ----------------------------------------------------

    def lookup(self, term: str) -> list[dict[str, Any]]:
        """Entries whose term or alias is exactly ``term`` (whitespace and case folded).

        Whole-name matches only: a partial match ("core" inside "core-lab" or "score") is a
        different word and would hand the model a definition the user did not ask for.
        """
        key = fold(term)
        if not key:
            return []
        rows = self._repo.find_by_name(key)[:MAX_LOOKUP_RESULTS]
        return [
            {"term": r.term, "aliases": list(r.aliases or []), "filter": dict(r.filter)}
            for r in rows
        ]


def _names(body: GlossaryTermCreate | GlossaryTermUpdate) -> list[str]:
    return [fold(body.term), *(fold(a) for a in body.aliases)]


def _values(body: GlossaryTermCreate | GlossaryTermUpdate, fixed: FilterInput) -> dict[str, Any]:
    return {
        "term": body.term,
        "term_key": fold(body.term),
        "aliases": list(body.aliases),
        "search_text": " ".join(_names(body)),
        "filter": fixed.model_dump(mode="json"),
        "note": body.note,
    }


async def _prepare_filter(
    filter_: FilterInput, reader: FieldValueReader
) -> tuple[FilterInput, list[str]]:
    """Structure checks, then values respelled as Nautobot spells them.

    Returns the fixed filter and warnings (none today: a value that cannot be checked is refused,
    because an unchecked value would be served to the model as the administrators' definition).
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
    return fixed, []


def _unverifiable(field: str) -> str:
    return (
        f"The {field} values could not be checked because Nautobot returned no names. "
        "Try again when the source is reachable."
    )
