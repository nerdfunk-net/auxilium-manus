"""Constant-time verification of inbound git-webhook authenticity.

* GitHub sends ``X-Hub-Signature-256: sha256=<hex>`` — HMAC-SHA256 of the raw
  request body keyed by the repo's configured webhook secret.
* GitLab sends ``X-Gitlab-Token: <token>`` — the shared secret verbatim.

Both are compared with :func:`hmac.compare_digest` so a mismatch takes the same
time regardless of where it diverges. See ``doc/CICD_PIPELINE.md`` §3.5.
"""

from __future__ import annotations

import hashlib
import hmac

GITHUB_SIGNATURE_HEADER = "X-Hub-Signature-256"
GITLAB_TOKEN_HEADER = "X-Gitlab-Token"


def verify_github_signature(secret: str, raw_body: bytes, header_value: str | None) -> bool:
    """True iff ``header_value`` is ``sha256=<hex>`` and the HMAC matches."""
    if not secret or not header_value or not header_value.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_value)


def verify_gitlab_token(secret: str, header_value: str | None) -> bool:
    """True iff the presented token equals the configured secret."""
    if not secret or not header_value:
        return False
    return hmac.compare_digest(secret, header_value)
