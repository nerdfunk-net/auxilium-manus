"""Mask credentials embedded in URLs inside free text (git errors, log lines)."""

from __future__ import annotations

import re

# ``scheme://user:token@host`` -> ``scheme://***@host``. Git errors often echo the
# remote URL, and GitService temporarily injects the token into it for http(s).
_URL_USERINFO = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)[^/\s@]+@")


def scrub_url_credentials(text: str) -> str:
    """Mask credentials embedded in any URL inside free-text (error messages)."""
    return _URL_USERINFO.sub(r"\g<scheme>***@", text)
