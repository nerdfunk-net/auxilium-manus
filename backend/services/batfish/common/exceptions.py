"""Batfish client exceptions."""

from __future__ import annotations


class BatfishError(Exception):
    """Base exception for Batfish operations."""


class BatfishValidationError(BatfishError):
    """Raised when config/input validation fails, or the coordinator rejects the request."""


class BatfishAPIError(BatfishError):
    """Raised when a call to the Batfish coordinator fails (RPC or transport error)."""
