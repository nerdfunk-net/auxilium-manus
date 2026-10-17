from __future__ import annotations


class ReportQueryError(ValueError):
    """The query is invalid for the dataset (unknown field, wrong type for an operator, ...)."""


class UnknownSourceError(LookupError):
    """No report source with that id."""
