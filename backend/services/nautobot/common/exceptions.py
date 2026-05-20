"""Nautobot API exceptions."""


class NautobotError(Exception):
    """Base exception for Nautobot operations."""


class NautobotAPIError(NautobotError):
    """Raised when a Nautobot API request fails."""


class NautobotNotFoundError(NautobotAPIError):
    """Raised when a Nautobot resource is not found."""


class NautobotValidationError(NautobotError):
    """Raised when configuration or input validation fails."""
