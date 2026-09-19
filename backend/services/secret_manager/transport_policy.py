"""Transport policy for Secret Manager connections (SM2).

One function, called from ``SecretManagerConnectionService`` on create/update
(``resolve_dns=True``) and from both client adapters at construction
(``resolve_dns=False`` -- rows that predate the check, and no DNS on the
worker hot path). Mirrors ``core/production_guards`` for ``VAULT_ADDR`` /
``VAULT_VERIFY_SSL`` (V1), but per row, because a connection is a DB record,
not an environment variable.
"""

from __future__ import annotations

from urllib.parse import urlparse

from core.config import settings
from core.safe_urls import UnsafeURLError, validate_outbound_http_url

# Which backend_config key carries the base URL for each backend.
URL_KEY_BY_BACKEND: dict[str, str] = {"openbao": "addr", "infisical": "site_url"}


def validate_connection_transport(
    *,
    backend: str,
    backend_config: dict,
    verify_ssl: bool,
    resolve_dns: bool,
) -> str:
    """Return the normalized base URL or raise ``ValueError``.

    - The URL must satisfy ``validate_outbound_http_url`` (no link-local /
      metadata / loopback-unless-allowed targets, no userinfo).
    - Outside ``development`` the scheme must be ``https`` and
      ``verify_ssl`` must be ``True``.
    """
    url_key = URL_KEY_BY_BACKEND.get(backend)
    if url_key is None:
        raise ValueError(f"Unknown secret manager backend: {backend!r}")
    raw_url = str(backend_config.get(url_key) or "").strip()
    try:
        safe_url = validate_outbound_http_url(raw_url, resolve_dns=resolve_dns)
    except UnsafeURLError as exc:
        raise ValueError(f"backend_config.{url_key}: {exc}") from exc

    if settings.environment == "development":
        return safe_url

    if urlparse(safe_url).scheme.lower() != "https":
        raise ValueError(
            f"backend_config.{url_key} must use https outside development"
        )
    if not verify_ssl:
        raise ValueError(
            "verify_ssl=false is not allowed outside development; "
            "use a CA-signed certificate or the development environment"
        )
    return safe_url
