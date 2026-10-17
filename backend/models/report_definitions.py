"""Request/response models for report definitions and snapshots (doc/REPORTS.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.mail import MAX_RECIPIENTS, clean_address
from models.reports import QueryResult, ReportQuery

Presentation = Literal["table", "number", "bar", "line"]
SnapshotStatus = Literal["complete", "partial"]
SectionStatus = Literal["ok", "error"]

MAX_SECTIONS = 20
MAX_SECTION_TEXT = 5000
# Rows kept per section in a snapshot; a query may return up to MAX_QUERY_LIMIT.
SNAPSHOT_ROW_CAP = 1000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportSection(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    query: ReportQuery
    presentation: Presentation = "table"
    text: str | None = Field(default=None, max_length=MAX_SECTION_TEXT)


def _unique_section_ids(sections: list[ReportSection]) -> list[ReportSection]:
    ids = [s.id for s in sections]
    if len(set(ids)) != len(ids):
        raise ValueError("section ids must be unique")
    return sections


def _clean_recipients(value: list[str]) -> list[str]:
    return list(dict.fromkeys(clean_address(item) for item in value))


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("name must not be blank")
    if "\r" in value or "\n" in value:
        raise ValueError("name must be a single line")
    return value


class ReportDefinitionCreate(_Strict):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    sections: list[ReportSection] = Field(default_factory=list, max_length=MAX_SECTIONS)
    template_id: int | None = Field(default=None, ge=1)
    # Addresses the Send dialog proposes when a snapshot of this report is mailed.
    default_recipients: list[str] = Field(default_factory=list, max_length=MAX_RECIPIENTS)

    _name = field_validator("name")(_clean_name)
    _sections = field_validator("sections")(_unique_section_ids)
    _recipients = field_validator("default_recipients")(_clean_recipients)


class ReportDefinitionUpdate(_Strict):
    """Partial update: only the fields that are sent change."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    sections: list[ReportSection] | None = Field(default=None, max_length=MAX_SECTIONS)
    # Send null to go back to the default template.
    template_id: int | None = Field(default=None, ge=1)
    default_recipients: list[str] | None = Field(default=None, max_length=MAX_RECIPIENTS)

    @field_validator("default_recipients")
    @classmethod
    def _recipients(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _clean_recipients(value)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        return None if value is None else _clean_name(value)

    @field_validator("sections")
    @classmethod
    def _unique_ids(cls, value: list[ReportSection] | None) -> list[ReportSection] | None:
        return None if value is None else _unique_section_ids(value)

    @model_validator(mode="after")
    def _not_empty(self) -> ReportDefinitionUpdate:
        if not self.model_fields_set:
            raise ValueError("nothing to update")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name must not be null")
        if "sections" in self.model_fields_set and self.sections is None:
            raise ValueError("sections must not be null")
        if "default_recipients" in self.model_fields_set and self.default_recipients is None:
            raise ValueError("default_recipients must not be null")
        return self


class ReportDefinitionResponse(_Strict):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    name: str
    description: str | None
    sections: list[ReportSection]
    template_id: int | None
    default_recipients: list[str] = Field(default_factory=list)
    created_by: int | None
    created_at: datetime
    updated_at: datetime

    @field_validator("default_recipients", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return [] if value is None else value


class ReportDefinitionSummary(_Strict):
    id: int
    name: str
    description: str | None
    section_count: int
    updated_at: datetime
    snapshot_count: int
    last_generated_at: datetime | None


# -- snapshots ----------------------------------------------------------------------------------


class SnapshotSection(_Strict):
    """One section of a snapshot: the definition's section plus what its query returned."""

    section: ReportSection
    status: SectionStatus
    result: QueryResult | None = None
    error: str | None = None
    # The result was cut to SNAPSHOT_ROW_CAP rows (or the query itself was truncated).
    truncated: bool = False


class SnapshotBody(_Strict):
    """The report rendered through its template: Markdown, or the reason there is none."""

    template_id: int | None = None
    # Empty for the built-in default template.
    template_name: str = ""
    markdown: str | None = None
    error: str | None = None


class SnapshotContent(_Strict):
    name: str
    description: str | None
    sections: list[SnapshotSection]
    # Absent in snapshots generated before report templates existed.
    body: SnapshotBody | None = None


class ReportSnapshotSummary(_Strict):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    definition_id: int | None
    name: str
    generated_by: str | None
    status: SnapshotStatus
    generated_at: datetime


class ReportSnapshotResponse(ReportSnapshotSummary):
    content: SnapshotContent


class TemplatePreviewRequest(_Strict):
    content: str = Field(max_length=200_000)


class TemplatePreviewResponse(_Strict):
    markdown: str | None
    error: str | None
