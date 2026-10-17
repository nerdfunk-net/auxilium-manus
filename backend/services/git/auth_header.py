"""HTTP Basic header value for git token auth (no heavy imports; used by ``services.git.env``)."""

from __future__ import annotations

import base64


def auth_header_value(username: str | None, token: str | None) -> str | None:
    """HTTP Basic value for ``http.<origin>/.extraHeader`` (same wire format as URL userinfo)."""
    if not token:
        return None
    raw = f"{username or 'git'}:{token}".encode()
    return "Authorization: Basic " + base64.b64encode(raw).decode("ascii")
