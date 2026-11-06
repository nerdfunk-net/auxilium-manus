"""Typed errors for the Cisco ACI (APIC) integration."""

from __future__ import annotations

from models.failure import FailureInfo


class AciError(Exception):
    """Base class for ACI integration errors.

    ``http_status`` and ``code`` are the structured facts behind the (human) message; they
    feed :attr:`failure`. ``code`` is one of the short strings listed in
    ``services.aci.common.failure`` - never text taken from a response.
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
        from services.aci.common.failure import classify_aci_exception

        return classify_aci_exception(self)


class AciValidationError(AciError):
    """Bad configuration or a request the APIC rejected (HTTP 400)."""


class AciAuthError(AciError):
    """Login failed, or the APIC refused the session or the user's rights (401/403)."""


class AciAPIError(AciError):
    """Transport failure or an unexpected APIC response."""


class AciRateLimitError(AciAPIError):
    """The APIC kept answering 429 (rate limited) after the bounded retries."""


class AciNotFoundError(AciAPIError):
    """The requested object or class does not exist (HTTP 404)."""


class AciTooManyDevicesError(AciValidationError):
    """A device search matched more devices than the configured cap allows."""

    def __init__(self, limit: int) -> None:
        super().__init__(
            f"Matched more than {limit} devices; narrow the filters or raise max_devices"
        )
        self.limit = limit
