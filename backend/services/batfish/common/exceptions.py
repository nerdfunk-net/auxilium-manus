"""Batfish client exceptions."""

from __future__ import annotations

from typing import Any


class BatfishError(Exception):
    """Base exception for Batfish operations."""


class BatfishValidationError(BatfishError):
    """Raised when config/input validation fails, or the coordinator rejects the request."""


class BatfishAPIError(BatfishError):
    """Raised when a call to the Batfish coordinator fails (RPC or transport error)."""


class BatfishAnswerFailedError(BatfishAPIError):
    """Raised when Batfish accepts and runs a question but can't produce a result table.

    pybatfish's ``Question.answer()`` returns a plain
    ``pybatfish.datamodel.answer.base.Answer`` (no ``.frame()``) rather than a
    ``TableAnswer`` -- and rather than raising -- whenever the coordinator can't
    build the requested table, most commonly because a node/location specifier
    (e.g. ``reachability``'s ``pathConstraints.startLocation``/``endLocation``,
    or ``testFilters``'s ``nodes``) doesn't resolve to anything in the snapshot.
    Calling ``.frame()`` unconditionally on that object crashes with an opaque
    ``AttributeError: 'Answer' object has no attribute 'frame'`` deep inside a
    background thread -- this exception replaces that crash with a typed,
    catchable signal. ``answer`` is the raw (non-table) answer dict, kept for
    callers that want to build a more specific message; ``BatfishService``
    itself does not attempt to parse it.
    """

    def __init__(self, question_name: str, answer: dict[str, Any]) -> None:
        self.question_name = question_name
        self.answer = answer
        super().__init__(
            f"Batfish question {question_name!r} did not return a result table -- "
            "this usually means a referenced node or location does not exist in "
            "the snapshot"
        )
