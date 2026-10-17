"""Shared TLS trust configuration for the backend's outbound httpx clients.

Builds an :class:`ssl.SSLContext` that trusts **both**:

* the OS trust store — so CAs installed at startup by :mod:`core.cert_installer`
  (``update-ca-certificates``, gated by ``INSTALL_CERTIFICATE_FILES``) are honoured; and
* the ``certifi`` bundle — so on macOS / local dev, where the store
  ``ssl.create_default_context()`` loads is near-empty, coverage matches what
  ``httpx.AsyncClient(verify=True)`` gave before.

The context is built lazily (first use, cached) so certificates installed during
process startup are already present when it is created.
"""

from __future__ import annotations

import logging
import ssl
from functools import lru_cache

import certifi

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def create_verified_ssl_context() -> ssl.SSLContext:
    """Return the process-wide TLS-verifying context (OS trust store + certifi)."""
    context = ssl.create_default_context()  # Linux: loads /etc/ssl/certs
    try:
        context.load_verify_locations(cafile=certifi.where())
    except OSError:
        logger.warning("certifi bundle not loadable; relying on OS trust store only")
    return context


def verify_option(verify_ssl: bool) -> ssl.SSLContext | bool:
    """``httpx``'s ``verify=`` value: the shared trusting context, or ``False``."""
    return create_verified_ssl_context() if verify_ssl else False
