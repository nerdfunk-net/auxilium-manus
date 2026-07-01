"""Nautobot API exceptions and shared error helpers."""

from __future__ import annotations

import logging


import logging

logger = logging.getLogger(__name__)


class NautobotError(Exception):
    """Base exception for Nautobot operations."""


class NautobotValidationError(NautobotError):
    """Raised when configuration or input validation fails."""


class NautobotAPIError(NautobotError):
    """Raised when a Nautobot API request fails."""


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
