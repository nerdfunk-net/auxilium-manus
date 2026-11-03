"""The signed confirmation token for a proposed workflow run (doc/AI_TOOL_CHAIN.md §16, §13.2).

``propose_workflow_run`` signs what the user is shown: who, which released workflow, the resolved
inputs and the devices. The confirm endpoint starts exactly that and nothing else, so the model (or
a tampered request) cannot change the inputs or the device list between the card and the click, and
one user's token is useless to another. The token holds no secret: secret-typed inputs are never
accepted from the model. The key is derived from the application secret.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from core.config import settings
from services.ai_assistant.released_run_builder import ProposedDevice

TOKEN_TTL_SECONDS = 600
MAX_TOKEN_CHARS = 16384
_KEY_CONTEXT = b"manus-ai-workflow-run-token-v1"


class InvalidRunTokenError(ValueError):
    """Malformed, forged, for another user or expired; never says which."""


@dataclass(frozen=True)
class WorkflowRunGrant:
    user_id: int
    workflow_id: int
    run_inputs: dict[str, Any]
    devices: tuple[ProposedDevice, ...]
    # The release this proposal was made against; the start refuses any other (or a changed) one.
    stamp: str
    # Random id so a confirmation can be used once.
    token_id: str
    expires_at: float


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError
    return value


def _device(raw: Any) -> ProposedDevice:
    if not isinstance(raw, dict):
        raise TypeError
    name, driver, platform = raw["n"], raw["r"], raw["p"]
    for value in (name, driver, platform):
        if value is not None and not isinstance(value, str):
            raise TypeError
    if not isinstance(raw["v"], bool):
        raise TypeError
    return ProposedDevice(
        ip=str(raw["i"]),
        name=name,
        in_inventory=raw["v"],
        network_driver=driver,
        platform=platform,
    )


def _sign(body: bytes) -> bytes:
    key = hashlib.sha256(_KEY_CONTEXT + settings.secret_key.encode("utf-8")).digest()
    return hmac.new(key, body, hashlib.sha256).digest()


def issue_run_token(
    *,
    user_id: int,
    workflow_id: int,
    run_inputs: dict[str, Any],
    devices: list[ProposedDevice],
    stamp: str,
    now: float | None = None,
) -> tuple[str, float]:
    """The token and its expiry (Unix seconds)."""
    expires_at = (time.time() if now is None else now) + TOKEN_TTL_SECONDS
    payload = {
        "u": user_id,
        "w": workflow_id,
        "i": run_inputs,
        "d": [
            {
                "i": d.ip,
                "n": d.name,
                "v": d.in_inventory,
                "r": d.network_driver,
                "p": d.platform,
            }
            for d in devices
        ],
        "s": stamp,
        "j": secrets.token_hex(16),
        "x": expires_at,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(body).decode("ascii")
    signature = base64.urlsafe_b64encode(_sign(encoded.encode("ascii"))).decode("ascii")
    return f"{encoded}.{signature}", expires_at


def verify_run_token(token: object, *, user_id: int, now: float | None = None) -> WorkflowRunGrant:
    """The grant, or ``InvalidRunTokenError``; the signature is checked before the payload."""
    if not isinstance(token, str) or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
        raise InvalidRunTokenError
    encoded, signature = token.split(".")
    try:
        given = base64.urlsafe_b64decode(signature.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise InvalidRunTokenError from exc
    if not hmac.compare_digest(given, _sign(encoded.encode("ascii", "replace"))):
        raise InvalidRunTokenError
    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
        inputs = payload["i"]
        if not isinstance(inputs, dict):
            raise TypeError
        grant = WorkflowRunGrant(
            user_id=int(payload["u"]),
            workflow_id=int(payload["w"]),
            run_inputs=inputs,
            devices=tuple(_device(d) for d in payload["d"]),
            stamp=_text(payload["s"]),
            token_id=_text(payload["j"]),
            expires_at=float(payload["x"]),
        )
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise InvalidRunTokenError from exc
    if grant.user_id != user_id or (time.time() if now is None else now) >= grant.expires_at:
        raise InvalidRunTokenError
    return grant
