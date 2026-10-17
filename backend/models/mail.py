"""Pydantic models for the global mail (SMTP) settings and sending a report by email."""

from __future__ import annotations

import re
from email.utils import parseaddr
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MailSecurity = Literal["none", "starttls", "ssl"]

_BARE_ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+$")
MAX_RECIPIENTS = 20
MAX_ALLOWED_DOMAINS = 50
_DOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")


def clean_address(value: str) -> str:
    """A bare ``user@host`` address, or ``ValueError``. Rejects display names and line breaks."""
    text = value.strip()
    if "\r" in text or "\n" in text:
        raise ValueError("an email address must be a single line")
    address = parseaddr(text)[1]
    if not _BARE_ADDRESS.match(address):
        raise ValueError(f"{text!r} is not a valid email address")
    return address


class MailSettings(BaseModel):
    """Global SMTP settings. The password is never stored here: ``credential_name`` names a global
    ``generic`` vault credential whose username and password are used to authenticate."""

    model_config = ConfigDict(extra="forbid")

    smtp_server: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    security: MailSecurity = "starttls"
    verify_tls: bool = True
    from_address: str = Field(default="", max_length=320)
    credential_name: str | None = Field(default=None, max_length=255)
    # Only these domains (and their subdomains) may receive reports; empty means any domain.
    allowed_recipient_domains: list[str] = Field(
        default_factory=list, max_length=MAX_ALLOWED_DOMAINS
    )

    @field_validator("allowed_recipient_domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        cleaned = []
        for item in value:
            domain = item.strip().lower().rstrip(".")
            if len(domain) > 253 or not _DOMAIN.match(domain):
                raise ValueError(f"{item!r} is not a domain name such as example.org")
            cleaned.append(domain)
        return list(dict.fromkeys(cleaned))

    @field_validator("smtp_server")
    @classmethod
    def _server(cls, value: str) -> str:
        value = value.strip()
        if any(ch.isspace() for ch in value) or "/" in value:
            raise ValueError("smtp_server must be a host name or address")
        return value

    @field_validator("from_address")
    @classmethod
    def _from(cls, value: str) -> str:
        return clean_address(value) if value.strip() else ""

    @field_validator("credential_name")
    @classmethod
    def _credential(cls, value: str | None) -> str | None:
        value = (value or "").strip()
        return value or None

    @model_validator(mode="after")
    def _no_password_in_clear(self) -> MailSettings:
        if self.credential_name and self.security == "none":
            # AUTH PLAIN/LOGIN only base64-encode the password; never send it over a cleartext link.
            raise ValueError(
                "A credential requires security starttls or ssl "
                "(refusing to send the SMTP password unencrypted)"
            )
        return self


class MailSettingsResponse(MailSettings):
    # Server and sender are set, so mail can be sent.
    configured: bool


class MailTestResult(BaseModel):
    ok: bool
    message: str


class SendSnapshotRequest(BaseModel):
    """Send a stored report snapshot by email."""

    model_config = ConfigDict(extra="forbid")

    to: list[str] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    subject: str | None = Field(default=None, max_length=200)
    # A short note above the report text.
    message: str | None = Field(default=None, max_length=2000)
    include_pdf: bool = True

    @field_validator("to")
    @classmethod
    def _recipients(cls, value: list[str]) -> list[str]:
        cleaned = [clean_address(item) for item in value]
        return list(dict.fromkeys(cleaned))

    @field_validator("subject")
    @classmethod
    def _subject(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if "\r" in value or "\n" in value:
            raise ValueError("the subject must be a single line")
        return value or None


class SendSnapshotResult(BaseModel):
    sent_to: list[str]
    pdf_attached: bool
