from __future__ import annotations

from models.failure import FailureInfo


class MailError(Exception):
    """Base class for mail errors. Messages are safe to show to users."""


class MailNotConfiguredError(MailError):
    """No SMTP server or sender address is set in the mail settings."""


class MailCredentialError(MailError):
    """The credential named in the mail settings cannot be used."""


class MailSendError(MailError):
    """The SMTP exchange failed. The message names the exception class and SMTP code only; server
    text may echo credentials and is never kept. ``failure`` is the classified cause."""

    def __init__(self, message: str = "", *, failure: FailureInfo | None = None) -> None:
        super().__init__(message)
        self.failure = failure


class MailRecipientNotAllowedError(MailError):
    """A recipient's domain is not in the allowed list of the mail settings."""
