"""The contract every report source implements."""

from __future__ import annotations

from typing import Protocol

from models.reports import DatasetInfo, QueryResult, ReportQuery


class ReportSource(Protocol):
    """A place report data can be queried from (today only the report database).

    ``describe`` lists what can be queried (datasets or collections with typed fields) and
    ``validate`` checks a query without running it (raises ``ReportQueryError``) and ``run``
    executes it. The UI and the AI assistant build queries from the description, so a new
    source needs no new query builder.
    """

    id: str
    label: str

    def describe(self) -> list[DatasetInfo]: ...

    def validate(self, query: ReportQuery) -> None: ...

    def run(self, query: ReportQuery) -> QueryResult: ...
