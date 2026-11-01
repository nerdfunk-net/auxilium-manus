"""The signed confirmation token for a proposed device command (doc/AI_TOOL_CHAIN.md §13.2).

``propose_device_command`` signs what it is about to show the user: who, which device, which
commands, until when. The confirm endpoint refuses anything that does not match, so the model (or a
tampered request) cannot change the command or the device between the card and the click, and one
user's token is useless to another. Replaying a token within its lifetime re-runs the same read-only
commands, which the rate limit bounds.

The token holds no credential. It holds the address the card showed, so the confirm step can
refuse a run when the inventory has moved the device since. The key is derived from the
application secret.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from core.config import settings

TOKEN_TTL_SECONDS = 600
MAX_TOKEN_CHARS = 4096
_KEY_CONTEXT = b"manus-ai-device-command-token-v1"


class InvalidTokenError(ValueError):
    """The token is malformed, forged, for another user or expired; never says which."""


@dataclass(frozen=True)
class DeviceCommandGrant:
    user_id: int
    source_id: str
    device_id: str
    device_name: str
    host: str
    commands: tuple[str, ...]
    expires_at: float


def _sign(body: bytes) -> bytes:
    key = hashlib.sha256(_KEY_CONTEXT + settings.secret_key.encode("utf-8")).digest()
    return hmac.new(key, body, hashlib.sha256).digest()


def issue_token(
    *,
    user_id: int,
    source_id: str,
    device_id: str,
    device_name: str,
    host: str,
    commands: list[str],
    now: float | None = None,
) -> tuple[str, float]:
    """The token and its expiry (Unix seconds)."""
    expires_at = (time.time() if now is None else now) + TOKEN_TTL_SECONDS
    payload = {
        "u": user_id,
        "s": source_id,
        "d": device_id,
        "n": device_name,
        "h": host,
        "c": list(commands),
        "x": expires_at,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(body).decode("ascii")
    signature = base64.urlsafe_b64encode(_sign(encoded.encode("ascii"))).decode("ascii")
    return f"{encoded}.{signature}", expires_at


def verify_token(token: object, *, user_id: int, now: float | None = None) -> DeviceCommandGrant:
    """The grant, or ``InvalidTokenError``. The signature is checked before the payload is read."""
    if not isinstance(token, str) or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
        raise InvalidTokenError
    encoded, signature = token.split(".")
    try:
        given = base64.urlsafe_b64decode(signature.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise InvalidTokenError from exc
    if not hmac.compare_digest(given, _sign(encoded.encode("ascii", "replace"))):
        raise InvalidTokenError
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
        grant = DeviceCommandGrant(
            user_id=int(payload["u"]),
            source_id=str(payload["s"]),
            device_id=str(payload["d"]),
            device_name=str(payload["n"]),
            host=str(payload["h"]),
            commands=tuple(str(c) for c in payload["c"]),
            expires_at=float(payload["x"]),
        )
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise InvalidTokenError from exc
    if grant.user_id != user_id or (time.time() if now is None else now) >= grant.expires_at:
        raise InvalidTokenError
    return grant
