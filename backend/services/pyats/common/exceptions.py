"""pyATS shim client exceptions."""

from __future__ import annotations

from models.failure import FailureInfo


class PyATSError(Exception):
    """Base exception for pyATS shim operations.

    ``http_status`` and ``code`` are the structured facts behind the message and feed
    :attr:`failure`. ``code`` is ``timeout`` or ``transport``; never text taken from a response.
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
        from services.pyats.common.failure import classify_pyats_exception

        return classify_pyats_exception(self)


class PyATSValidationError(PyATSError):
    """Raised when config/input validation fails, or the shim rejects the request (400)."""


class PyATSAPIError(PyATSError):
    """Raised when a pyATS shim HTTP request fails."""
