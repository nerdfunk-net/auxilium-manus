"""Cisco ISE ERS API exceptions."""

from __future__ import annotations

from models.failure import FailureInfo


class ISEError(Exception):
    """Base exception for Cisco ISE operations.

    ``http_status`` and ``code`` are the structured facts behind the message and feed
    :attr:`failure`. ``code`` is ``timeout``, ``transport`` or ``invalid_response``; never text
    taken from a response.
    """

    def __init__(
        self, message: str = "", *, http_status: int | None = None, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.code = code

    @property
    def failure(self) -> FailureInfo:
        """Structured, non-sensitive classification (see ``models.failure``)."""
        from services.ise.common.failure import classify_ise_exception

        return classify_ise_exception(self)


class ISEValidationError(ISEError):
    """Raised when configuration or input validation fails, or ISE rejects the request (400)."""


class ISEAPIError(ISEError):
    """Raised when a Cisco ISE ERS API request fails."""


class ISENotFoundError(ISEAPIError):
    """Raised when a Cisco ISE resource is not found (404)."""
