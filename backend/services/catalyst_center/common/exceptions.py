"""Typed errors for the Cisco Catalyst Center integration."""

from __future__ import annotations

from models.failure import FailureInfo


class CatalystCenterError(Exception):
    """Base class for Catalyst Center integration errors.

    ``http_status`` and ``code`` are the structured facts behind the (human) message; they
    feed :attr:`failure`. ``code`` is one of the short strings listed in
    ``services.catalyst_center.common.failure`` - never text taken from a response.
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
        from services.catalyst_center.common.failure import classify_catalyst_center_exception

        return classify_catalyst_center_exception(self)


class CatalystCenterValidationError(CatalystCenterError):
    """Bad configuration or a request Catalyst Center rejected (HTTP 400)."""


class CatalystCenterAuthError(CatalystCenterError):
    """Token request failed, or the controller refused the credentials (401/403)."""


class CatalystCenterAPIError(CatalystCenterError):
    """Transport failure or an unexpected Catalyst Center response."""


class CatalystCenterRateLimitError(CatalystCenterAPIError):
    """Catalyst Center kept answering 429 (rate limited) after the bounded retries."""


class CatalystCenterNotFoundError(CatalystCenterAPIError):
    """The requested resource does not exist (HTTP 404)."""


class CatalystCenterTaskError(CatalystCenterAPIError):
    """An asynchronous Catalyst Center task failed or did not finish in time."""


class CatalystCenterTooManyDevicesError(CatalystCenterValidationError):
    """A device search matched more devices than the configured cap allows."""

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"Matched more than {limit} devices; narrow the filters or raise max_devices"
        )
        self.limit = limit
