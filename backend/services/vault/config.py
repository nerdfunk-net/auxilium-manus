"""Immutable configuration for one OpenBao client instance.

Two instances are built from :mod:`core.vault`: a read-only *runtime* config
(``role_label="manus-app"``) and a write-capable *management* config
(``role_label="manus-manage"``). Everything here comes from environment variables
via :class:`core.config.Settings` — never from a Settings-KV row or from OpenBao
itself.
"""

from __future__ import annotations

from dataclasses import dataclass

VALID_AUTH_METHODS = frozenset({"approle", "cert", "token"})


@dataclass(frozen=True)
class VaultConfig:
    """Connection + auth + token-lifecycle settings for one OpenBao client."""

    addr: str
    mount: str = "manus"
    namespace: str = ""
    auth_method: str = "approle"  # approle | cert | token

    # AppRole
    role_id: str = ""
    secret_id: str = ""
    secret_id_file: str = ""

    # Dev-only static token
    token: str = ""

    # Cert (mTLS) auth
    client_cert: str = ""
    client_key: str = ""
    ca_cert: str = ""

    verify_ssl: bool = True

    token_period_seconds: int = 3600
    renew_buffer_seconds: int = 600
    timeout_seconds: int = 5
    cache_ttl_seconds: int = 45

    # Human-readable label used only in log lines (runtime vs management).
    role_label: str = "manus-app"

    def resolved_secret_id(self) -> str:
        """Return the SecretID, reading ``secret_id_file`` when set.

        The file form is the manual ops-bootstrap delivery path: an operator
        drops the SecretID into a file that is bind-mounted / injected as a
        Docker secret, and rotates it in place.
        """
        if self.secret_id:
            return self.secret_id
        if self.secret_id_file:
            with open(self.secret_id_file, encoding="utf-8") as handle:
                return handle.read().strip()
        return ""
