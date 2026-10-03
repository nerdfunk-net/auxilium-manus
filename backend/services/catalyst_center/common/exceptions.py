"""Typed errors for the Cisco Catalyst Center integration."""

from __future__ import annotations


class CatalystCenterError(Exception):
    """Base class for Catalyst Center integration errors."""


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
