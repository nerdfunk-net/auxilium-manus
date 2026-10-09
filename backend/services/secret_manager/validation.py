"""Input rules for the pieces of a Secret Manager request that end up in a URL path."""

from __future__ import annotations

import re

# Starts alphanumeric/underscore, so "." and ".." can never match.
_FIELD_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}$")
_PATH_CHARS_RE = re.compile(r"^[A-Za-z0-9 _.@=+/-]+$")


def validate_field(field: str) -> str:
    """A secret key/field name."""
    if not _FIELD_RE.fullmatch(field):
        raise ValueError(
            "field must be 1-255 characters of letters, digits, '_', '.', '-' "
            "and must not start with '.' or '-'"
        )
    return field


def validate_kv_path(path: str) -> str:
    """A *rendered* secret path (after device-template substitution)."""
    segments = path.split("/")
    if (
        not path
        or path.startswith("/")
        or not _PATH_CHARS_RE.fullmatch(path)
        or any(segment in ("", ".", "..") for segment in segments)
    ):
        raise ValueError(
            f"invalid secret path {path!r}: use letters, digits, space and _ . @ = + - "
            "with '/' separators, no empty, '.' or '..' segments"
        )
    return path
