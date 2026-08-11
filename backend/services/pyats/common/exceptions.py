"""pyATS shim client exceptions."""

from __future__ import annotations


class PyATSError(Exception):
    """Base exception for pyATS shim operations."""


class PyATSValidationError(PyATSError):
    """Raised when config/input validation fails, or the shim rejects the request (400)."""


class PyATSAPIError(PyATSError):
    """Raised when a pyATS shim HTTP request fails."""
