"""Authenticated encryption for messages between the app and an agent.

One AEAD protects the whole message, so a message that opens is confidential, untampered and
known to come from a holder of the agent secret. The wire format is the same JSON object on
HTTP and on Redis::

    {"v": 1, "agent_id": ..., "command_id": ..., "direction": "request" | "response",
     "iat": <unix>, "exp": <unix>, "nonce": <b64url>, "ct": <b64url>}

* Key: HKDF-SHA256(agent secret, info = ``manus-agent/v1/<direction>/<agent_id>``), so the
  request and response directions use different keys and a response cannot be replayed as a
  request. The agent secret is generated with high entropy, which is why there is no password
  stretching here (``core.passphrase_cipher`` does that for human passphrases).
* AAD: the canonical header (everything except ``nonce`` and ``ct``), so the ids, the direction
  and the validity window cannot be changed without failing the tag check.
* Replay: ``exp`` bounds a message's life; the receiving agent also remembers seen
  ``command_id`` values until ``exp`` (see ``agent/<name>/manus_agent``).

``agent/<name>/manus_agent/envelope.py`` is a standalone copy of this module (an agent must not
import the backend); ``tests/unit/fixtures/agent_envelope_vectors.json`` is run against both and
``tests/unit/test_agent_envelope_sync.py`` fails when the two copies drift apart.
Error messages never contain the secret or payload.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Literal

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Must equal backend/core/secret_policy.py::MIN_AGENT_SECRET_LENGTH (a sync test pins it).
MIN_AGENT_SECRET_LENGTH = 32
PROTOCOL_VERSION = 1
MAX_CLOCK_SKEW_SECONDS = 60

Direction = Literal["request", "response"]
_DIRECTIONS: frozenset[str] = frozenset({"request", "response"})
_NONCE_BYTES = 12
_HEADER_FIELDS = ("v", "agent_id", "command_id", "direction", "iat", "exp")


class EnvelopeError(ValueError):
    """A malformed, forged, mismatched or otherwise unusable message."""


class EnvelopeExpiredError(EnvelopeError):
    """The message is outside its validity window."""


class EnvelopePayloadError(EnvelopeError):
    """The message authenticated and decrypted, but its payload is not a usable JSON object.

    Not an authentication failure: whoever sent it holds the secret.
    """


@dataclass(frozen=True)
class OpenedMessage:
    agent_id: str
    command_id: str
    direction: Direction
    issued_at: int
    expires_at: int
    payload: dict[str, Any]


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: Any) -> bytes:
    if not isinstance(text, str):
        raise EnvelopeError("malformed message: bad base64 field")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise EnvelopeError("malformed message: bad base64 field") from exc


def _check_secret(secret: str) -> bytes:
    if not isinstance(secret, str) or len(secret) < MIN_AGENT_SECRET_LENGTH:
        raise EnvelopeError(f"agent secret must be at least {MIN_AGENT_SECRET_LENGTH} characters")
    return secret.encode("utf-8")


def _hkdf(secret: bytes, info: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info.encode("utf-8")).derive(
        secret
    )


def _message_key(secret: str, direction: str, agent_id: str) -> bytes:
    return _hkdf(_check_secret(secret), f"manus-agent/v{PROTOCOL_VERSION}/{direction}/{agent_id}")


def derive_http_token(secret: str, agent_id: str) -> str:
    """Bearer token for the HTTP transport: a cheap pre-check, not the security boundary."""
    return _b64e(_hkdf(_check_secret(secret), f"manus-agent/v{PROTOCOL_VERSION}/token/{agent_id}"))


def _aad(header: dict[str, Any]) -> bytes:
    canonical = {name: header[name] for name in _HEADER_FIELDS}
    return json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")


def seal(
    payload: dict[str, Any],
    *,
    secret: str,
    agent_id: str,
    command_id: str,
    direction: Direction,
    ttl_seconds: int,
    now: int | None = None,
    nonce: bytes | None = None,
) -> dict[str, Any]:
    """Encrypt *payload* into a wire envelope. ``now`` and ``nonce`` exist for test vectors."""
    if direction not in _DIRECTIONS:
        raise EnvelopeError("unknown direction")
    if not agent_id or not command_id:
        raise EnvelopeError("agent_id and command_id are required")
    if ttl_seconds < 1:
        raise EnvelopeError("ttl_seconds must be positive")
    try:
        plaintext = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EnvelopeError("payload is not JSON serialisable") from exc

    issued_at = int(time.time()) if now is None else now
    header: dict[str, Any] = {
        "v": PROTOCOL_VERSION,
        "agent_id": agent_id,
        "command_id": command_id,
        "direction": direction,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    nonce_bytes = os.urandom(_NONCE_BYTES) if nonce is None else nonce
    key = _message_key(secret, direction, agent_id)
    ciphertext = AESGCM(key).encrypt(nonce_bytes, plaintext, _aad(header))
    return {**header, "nonce": _b64e(nonce_bytes), "ct": _b64e(ciphertext)}


def open_envelope(
    envelope: dict[str, Any],
    *,
    secret: str,
    expected_agent_id: str,
    expected_direction: Direction,
    expected_command_id: str | None = None,
    now: int | None = None,
    max_skew_seconds: int = MAX_CLOCK_SKEW_SECONDS,
) -> OpenedMessage:
    """Verify and decrypt *envelope*; raise ``EnvelopeError`` on anything unexpected."""
    if not isinstance(envelope, dict):
        raise EnvelopeError("malformed message: not an object")
    if envelope.get("v") != PROTOCOL_VERSION:
        raise EnvelopeError("unsupported protocol version")
    if any(name not in envelope for name in (*_HEADER_FIELDS, "nonce", "ct")):
        raise EnvelopeError("malformed message: missing field")

    iat, exp = envelope["iat"], envelope["exp"]
    if (
        isinstance(iat, bool)
        or isinstance(exp, bool)
        or not isinstance(iat, int)
        or not isinstance(exp, int)
    ):
        raise EnvelopeError("malformed message: bad timestamps")
    if envelope["direction"] != expected_direction:
        raise EnvelopeError("unexpected message direction")
    if envelope["agent_id"] != expected_agent_id:
        raise EnvelopeError("message is for a different agent")
    if expected_command_id is not None and envelope["command_id"] != expected_command_id:
        raise EnvelopeError("message answers a different command")

    current = int(time.time()) if now is None else now
    if exp < current:
        raise EnvelopeExpiredError("message expired")
    if iat > current + max_skew_seconds:
        raise EnvelopeError("message issued in the future (check clock synchronisation)")

    key = _message_key(secret, expected_direction, expected_agent_id)
    try:
        plaintext = AESGCM(key).decrypt(
            _b64d(envelope["nonce"]), _b64d(envelope["ct"]), _aad(envelope)
        )
    except InvalidTag as exc:
        raise EnvelopeError(
            "message authentication failed (wrong secret or tampered data)"
        ) from exc
    except ValueError as exc:
        raise EnvelopeError("malformed message: bad nonce or ciphertext") from exc

    try:
        payload = json.loads(plaintext)
    except (ValueError, RecursionError) as exc:  # RecursionError: absurdly deep nesting
        raise EnvelopePayloadError("payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise EnvelopePayloadError("payload must be a JSON object")

    return OpenedMessage(
        agent_id=envelope["agent_id"],
        command_id=envelope["command_id"],
        direction=expected_direction,
        issued_at=iat,
        expires_at=exp,
        payload=payload,
    )
