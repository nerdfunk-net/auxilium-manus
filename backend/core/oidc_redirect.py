"""OIDC redirect_uri policy: allow-listed in production, narrow defaults in development."""

from __future__ import annotations

from urllib.parse import urlparse

_DEV_HOSTS = frozenset({"localhost", "127.0.0.1"})
_DEV_PATHS = frozenset({"/login/callback", "/login/oidc-test-callback"})


def validate_oidc_redirect_uri(
    redirect_uri: str,
    *,
    allowlist: list[str],
    environment: str,
    dev_tools: bool = False,
) -> str:
    """Return the URI or raise ``ValueError``."""
    raw = (redirect_uri or "").strip()
    if not raw:
        raise ValueError("redirect_uri is required")

    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("redirect_uri must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("redirect_uri must not contain embedded credentials")
    if parsed.fragment:
        raise ValueError("redirect_uri must not contain a fragment")

    if dev_tools:
        return raw

    normalized_allowlist = [entry.strip() for entry in allowlist if entry.strip()]
    if normalized_allowlist:
        if raw not in normalized_allowlist:
            raise ValueError("redirect_uri is not allow-listed")
        return raw

    if environment != "development":
        raise ValueError("OIDC_REDIRECT_URI_ALLOWLIST is required outside development")

    if parsed.hostname not in _DEV_HOSTS or parsed.path not in _DEV_PATHS:
        raise ValueError("redirect_uri is not allowed in development")
    return raw


def assert_redirect_matches_state(stored: str | None, incoming: str) -> None:
    """Raise ``ValueError`` unless ``incoming`` matches the redirect_uri bound to state."""
    if stored is None or incoming != stored:
        raise ValueError("redirect_uri does not match the value bound to this login attempt")
