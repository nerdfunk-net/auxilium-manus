"""Assistant glossary: admin-managed words that expand into something the assistants can use.

An entry has a ``kind``: ``inventory_filter`` (a word -> a small structured filter, values checked
against Nautobot) or ``workflow_step`` (a word -> one registry step id). Validation per kind is in
``glossary_kinds``. The model receives the entry as data through ``get_glossary`` and is told to
apply it, so nothing free-text is stored for it (doc/ai_integration/AI_ASSISTANT.md).
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

from sqlalchemy.orm import Session

from core.domain_exceptions import ConflictError, NotFoundError, ValidationFailedError
from core.models.ai_glossary import AiGlossaryTerm
from models.ai_glossary import (
    GlossaryListResponse,
    GlossaryTermResponse,
    InventoryTermBody,
    StepAliasBody,
)
from repositories.ai_glossary_repository import AiGlossaryRepository
from services.ai_assistant.glossary_kinds import SaveContext, fold, prepare_payload

logger = logging.getLogger(__name__)

MAX_TERMS = 500  # per kind
MAX_LOOKUP_RESULTS = 10
MAX_SUGGESTIONS = 5
SUGGEST_CUTOFF = 0.6
MIN_CONTAINED = 4  # a shorter name inside a long phrase is too weak a hint

TermBody = InventoryTermBody | StepAliasBody


def _to_response(row: AiGlossaryTerm) -> GlossaryTermResponse:
    return GlossaryTermResponse(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]  # the column holds one of the two kinds
        term=row.term,
        aliases=list(row.aliases or []),
        payload=dict(row.payload),
        note=row.note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class GlossaryService:
    def __init__(self, db: Session) -> None:
        self._repo = AiGlossaryRepository(db)

    # -- admin reads ---------------------------------------------------------

    def list_terms(
        self, kind: str, query: str | None, limit: int, offset: int
    ) -> GlossaryListResponse:
        rows = self._repo.search(kind, query, limit, offset)
        return GlossaryListResponse(
            items=[_to_response(r) for r in rows], total=self._repo.count(kind, query)
        )

    # -- admin writes --------------------------------------------------------

    async def create(
        self, body: TermBody, context: SaveContext, actor_user_id: int
    ) -> GlossaryTermResponse:
        if self._repo.count(body.kind) >= MAX_TERMS:
            raise ConflictError(f"The glossary is limited to {MAX_TERMS} terms per kind")
        self._check_names_free(body, own_id=None)
        payload = await prepare_payload(body, context)
        row = self._repo.create(_values(body, payload), _names(body), created_by_id=actor_user_id)
        logger.info(
            "AI glossary term created id=%s kind=%s by user_id=%s", row.id, row.kind, actor_user_id
        )
        return _to_response(row)

    async def update(
        self, term_id: int, body: TermBody, context: SaveContext, actor_user_id: int
    ) -> GlossaryTermResponse:
        row = self._repo.get(term_id)
        if row is None:
            raise NotFoundError("Glossary term not found")
        if row.kind != body.kind:
            raise ValidationFailedError("The kind of a glossary term cannot be changed")
        self._check_names_free(body, own_id=term_id)
        payload = await prepare_payload(body, context)
        row = self._repo.update(row, _update_values(body, payload), _names(body))
        logger.info("AI glossary term updated id=%s by user_id=%s", row.id, actor_user_id)
        return _to_response(row)

    def delete(self, term_id: int, actor_user_id: int) -> None:
        row = self._repo.get(term_id)
        if row is None:
            raise NotFoundError("Glossary term not found")
        self._repo.delete(row)
        logger.info("AI glossary term deleted id=%s by user_id=%s", term_id, actor_user_id)

    def _check_names_free(self, body: TermBody, own_id: int | None) -> None:
        wanted = _names(body)
        if len(set(wanted)) != len(wanted):
            raise ValidationFailedError("A term and its aliases must all be different")
        clash = self._repo.names_in_use(body.kind, wanted, own_id)
        if clash:
            raise ConflictError(f"'{clash[0]}' is already used by another glossary term")

    # -- assistant lookup ----------------------------------------------------

    def lookup(self, kind: str, term: str) -> list[dict[str, Any]]:
        """Entries of ``kind`` whose term or alias is exactly ``term`` (whitespace, case folded).

        Whole-name matches only: a partial match ("core" inside "core-lab" or "score") is a
        different word and would hand the model a definition the user did not ask for.
        """
        key = fold(term)
        if not key:
            return []
        rows = self._repo.find_by_name(kind, key)[:MAX_LOOKUP_RESULTS]
        return [
            {"term": r.term, "aliases": list(r.aliases or []), "payload": dict(r.payload)}
            for r in rows
        ]

    def suggest(self, kind: str, term: str) -> list[str]:
        """Names of ``kind`` close to ``term``, for a lookup that found nothing.

        Only the word is returned (no payload): the model must look an exact name up to get a
        definition, so a near miss never hands it something the user did not ask for.
        """
        key = fold(term)
        if not key:
            return []
        return _close_names(key, self._repo.names_of_kind(kind))


def _close_names(key: str, names: list[str]) -> list[str]:
    """The names most like ``key``: close spelling, or one contains the other."""
    close = difflib.get_close_matches(key, names, n=MAX_SUGGESTIONS, cutoff=SUGGEST_CUTOFF)
    contained = [n for n in names if len(n) >= MIN_CONTAINED and (n in key or key in n)]
    return list(dict.fromkeys([*close, *contained]))[:MAX_SUGGESTIONS]


def _names(body: TermBody) -> list[str]:
    return [fold(body.term), *(fold(a) for a in body.aliases)]


def _update_values(body: TermBody, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "term": body.term,
        "term_key": fold(body.term),
        "aliases": list(body.aliases),
        "search_text": " ".join(_names(body)),
        "payload": payload,
        "note": body.note,
    }


def _values(body: TermBody, payload: dict[str, Any]) -> dict[str, Any]:
    return {"kind": body.kind, **_update_values(body, payload)}
