"""Mattermost client exceptions."""

from __future__ import annotations

from models.failure import FailureInfo


class MattermostError(Exception):
    """Base exception for Mattermost operations."""


class MattermostValidationError(MattermostError):
    """Raised when config/input validation fails, or Mattermost rejects the request (400)."""


class MattermostAPIError(MattermostError):
    """Raised when a Mattermost HTTP request fails.

    ``failure`` is the closed-vocabulary record of the cause (never free text); the steps copy it
    onto the outcome they return.
    """

    def __init__(self, message: str = "", *, failure: FailureInfo | None = None) -> None:
        super().__init__(message)
        self.failure = failure
