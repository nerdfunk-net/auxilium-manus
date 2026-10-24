"""Nautobot API exceptions and shared error helpers."""

from __future__ import annotations

import logging

from models.failure import FailureInfo

logger = logging.getLogger(__name__)


class NautobotError(Exception):
    """Base exception for Nautobot operations.

    ``http_status`` and ``code`` (``timeout`` or ``transport``) are the structured facts behind
    the message and feed :attr:`failure`; never text taken from a response. The one exception is
    a REST 400 with structured validation JSON, whose cleaned, capped text is appended to the
    message (``response_detail.validation_detail``); ``failure`` never copies message text.
    """

    def __init__(
        self,
        message: str = "",
        *,
        http_status: int | None = None,
        code: str | None = None,
        fields: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        # Top-level field names of a structured REST 400 validation body (``__all__`` = the whole
        # object), or None when the error carried none.
        self.fields = fields

    @property
    def failure(self) -> FailureInfo:
        """Structured, non-sensitive classification (see ``models.failure``)."""
        from services.nautobot.common.failure import classify_nautobot_exception

        return classify_nautobot_exception(self)


class NautobotValidationError(NautobotError):
    """Raised when configuration or input validation fails."""


class NautobotAPIError(NautobotError):
    """Raised when a Nautobot API request fails."""


class NautobotAmbiguousMatchError(NautobotError):
    """More than one Nautobot object matches one workflow device (C3-03)."""


class NautobotNotFoundError(NautobotAPIError):
    """Raised when a Nautobot resource is not found."""


class NautobotResourceNotFoundError(NautobotError):
    """Resource not found in Nautobot."""

    def __init__(self, resource_type: str, identifier: str) -> None:
        self.resource_type = resource_type
        self.identifier = identifier
        super().__init__(f"{resource_type} not found: {identifier}")


class NautobotDuplicateResourceError(NautobotError):
    """Resource already exists."""

    def __init__(self, resource_type: str, identifier: str) -> None:
        self.resource_type = resource_type
        self.identifier = identifier
        super().__init__(f"{resource_type} already exists: {identifier}")


def is_duplicate_error(error: Exception) -> bool:
    error_msg = str(error).lower()
    duplicate_keywords = ["already exists", "duplicate", "unique constraint"]
    return any(keyword in error_msg for keyword in duplicate_keywords)


def handle_already_exists_error(error: Exception, resource_type: str) -> dict[str, str]:
    error_msg = str(error)
    logger.warning("%s already exists: %s", resource_type, error_msg)
    return {
        "error": "already_exists",
        "message": f"{resource_type} already exists",
        "detail": error_msg,
    }
