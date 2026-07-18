"""Cisco ISE ERS API exceptions."""

from __future__ import annotations


class ISEError(Exception):
    """Base exception for Cisco ISE operations."""


class ISEValidationError(ISEError):
    """Raised when configuration or input validation fails, or ISE rejects the request (400)."""


class ISEAPIError(ISEError):
    """Raised when a Cisco ISE ERS API request fails."""


class ISENotFoundError(ISEAPIError):
    """Raised when a Cisco ISE resource is not found (404)."""
