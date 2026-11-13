"""The signed confirmation token for a proposed report (doc/AI_TOOL_CHAIN.md §53, §13.2).

``propose_report`` signs what the user is shown: who, and the whole report (name, sections with
their queries, template). The confirm endpoint generates exactly that and nothing else, so the
model (or a tampered request) cannot change a query between the card and the click, and one
user's token is useless to another. The token holds no secret and generating a report only reads
and stores a snapshot, so unlike a workflow start it is not single-use: a second click makes a
second snapshot, bounded by the endpoint's rate limit and the per-user snapshot cap. The key is
derived from the application secret (and differs from the workflow token's key).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from pydantic import ValidationError

from core.config import settings
from models.report_definitions import ReportDefinitionCreate

TOKEN_TTL_SECONDS = 600
# Twenty sections with a query each fit comfortably; the request model allows the same size.
MAX_TOKEN_CHARS = 65536
_KEY_CONTEXT = b"manus-ai-report-run-token-v1"


class InvalidReportTokenError(ValueError):
    """Malformed, forged, for another user or expired; never says which."""


@dataclass(frozen=True)
class ReportGrant:
    user_id: int
    report: ReportDefinitionCreate
    expires_at: float


def _sign(body: bytes) -> bytes:
    key = hashlib.sha256(_KEY_CONTEXT + settings.secret_key.encode("utf-8")).digest()
    return hmac.new(key, body, hashlib.sha256).digest()


def issue_report_token(
    *, user_id: int, report: ReportDefinitionCreate, now: float | None = None
) -> tuple[str, float]:
    """The token and its expiry (Unix seconds)."""
    expires_at = (time.time() if now is None else now) + TOKEN_TTL_SECONDS
    payload = {"u": user_id, "r": report.model_dump(mode="json"), "x": expires_at}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(body).decode("ascii")
    signature = base64.urlsafe_b64encode(_sign(encoded.encode("ascii"))).decode("ascii")
    return f"{encoded}.{signature}", expires_at


def verify_report_token(token: object, *, user_id: int, now: float | None = None) -> ReportGrant:
    """The grant, or ``InvalidReportTokenError``; the signature is checked before the payload."""
    if not isinstance(token, str) or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
        raise InvalidReportTokenError
    encoded, signature = token.split(".")
    try:
        given = base64.urlsafe_b64decode(signature.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise InvalidReportTokenError from exc
    if not hmac.compare_digest(given, _sign(encoded.encode("ascii", "replace"))):
        raise InvalidReportTokenError
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
        grant = ReportGrant(
            user_id=int(payload["u"]),
            report=ReportDefinitionCreate.model_validate(payload["r"]),
            expires_at=float(payload["x"]),
        )
    except (binascii.Error, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise InvalidReportTokenError from exc
    if grant.user_id != user_id or (time.time() if now is None else now) >= grant.expires_at:
        raise InvalidReportTokenError
    return grant
