"""Mattermost client exceptions."""

from __future__ import annotations


class MattermostError(Exception):
    """Base exception for Mattermost operations."""


class MattermostValidationError(MattermostError):
    """Raised when config/input validation fails, or Mattermost rejects the request (400)."""


class MattermostAPIError(MattermostError):
    """Raised when a Mattermost HTTP request fails."""
