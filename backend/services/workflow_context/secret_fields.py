"""Seal, unwrap, and redact sensitive workflow attribute values.

TACACS shared secrets (and similar) may ride in ``DeviceContext.attribute_bags``
for in-run use, but must never appear as cleartext in persisted step results
(``WorkflowStepResult.output``), log-attributes dumps, or INFO logs.

Data-flow:

- **Sealed** (at rest in bags / in-memory between steps): a Fernet envelope
  produced by :func:`seal_secret`, reusing the same key material as
  credential-table encryption (``core.crypto.EncryptionService``).
- **Exported** (DB step output, log-attributes files, workflow-log metadata,
  any run API): always the literal ``***REDACTED***`` placeholder via
  :func:`redact_secrets_in_data` — never even ciphertext.
- **Consumed** (attribute resolution, Jinja namespace, ISE update payloads):
  unwrapped to cleartext only in process memory for the duration of the call,
  via :func:`unwrap_secret`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.crypto import EncryptionService

SEALED_MARKER = "__am_sealed__"
REDACTED_PLACEHOLDER = "***REDACTED***"

# Dotted paths relative to a device's attribute_bags that are treated as
# secret-valued regardless of whether the leaf is sealed or (legacy) plain
# cleartext.
SECRET_BAG_PATHS: tuple[tuple[str, ...], ...] = (
    ("tacacs", "shared_secret"),
    ("ise", "tacacsSettings", "sharedSecret"),
)


def path_is_known_secret(dotted_path: str) -> bool:
    """True when *dotted_path* (e.g. ``"tacacs.shared_secret"``) is a known secret path."""
    parts = tuple(part for part in dotted_path.strip().split(".") if part)
    return parts in SECRET_BAG_PATHS


def seal_secret(plaintext: str, *, encryption: EncryptionService | None = None) -> dict[str, Any]:
    """Encrypt *plaintext* into a sealed envelope suitable for storage in an attribute bag."""
    svc = encryption or EncryptionService()
    token = svc.encrypt(plaintext)
    return {SEALED_MARKER: True, "v": 1, "ct": token.decode("ascii")}


def is_sealed_secret(value: Any) -> bool:
    """True when *value* is a sealed envelope produced by :func:`seal_secret`."""
    return isinstance(value, dict) and value.get(SEALED_MARKER) is True and "ct" in value


def unwrap_secret(value: Any, *, encryption: EncryptionService | None = None) -> str | None:
    """Return cleartext for a sealed envelope, pass through a legacy cleartext
    string as-is (migration safety), else ``None``.

    Raises ``ValueError`` if the envelope cannot be decrypted (e.g. the
    encryption key has been rotated since it was sealed) — callers must let
    this propagate as a step failure rather than silently treating the
    secret as absent.
    """
    if value is None:
        return None
    if is_sealed_secret(value):
        svc = encryption or EncryptionService()
        return svc.decrypt(str(value["ct"]).encode("ascii"))
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def secret_is_present(value: Any) -> bool:
    """True when a bag leaf holds a usable secret (sealed or legacy cleartext),
    without decrypting it."""
    if is_sealed_secret(value):
        return True
    return bool(isinstance(value, str) and value.strip())


def redact_secrets_in_data(data: Any) -> Any:
    """Deep-copy *data* and replace known secret leaves / sealed envelopes
    with :data:`REDACTED_PLACEHOLDER`.

    Two independent mechanisms, combined:

    1. Any ``attribute_bags`` dict found anywhere in the structure has its
       :data:`SECRET_BAG_PATHS` leaves redacted, whether the leaf is sealed
       or (legacy) plain cleartext.
    2. Any sealed envelope found anywhere in the structure — even outside an
       ``attribute_bags`` dict — is redacted too.

    Limitation: this is shape/marker based, not content based. A secret that
    has been unwrapped to cleartext by a step and copied into a differently
    shaped output (a diff entry, a filtered list, a free-text message) is a
    bare string this function cannot recognize. Steps that resolve secret
    values must not do this — see ``doc/WORKFLOW-STEPS.md``.
    """
    cloned = deepcopy(data)
    _redact_inplace(cloned)
    return cloned


def _redact_inplace(node: Any) -> None:
    if isinstance(node, dict):
        bags = node.get("attribute_bags")
        if isinstance(bags, dict):
            _redact_bag_paths(bags)
        for key, value in list(node.items()):
            if is_sealed_secret(value):
                node[key] = REDACTED_PLACEHOLDER
            else:
                _redact_inplace(value)
    elif isinstance(node, list):
        for item in node:
            _redact_inplace(item)


def _redact_bag_paths(bags: dict[str, Any]) -> None:
    for path in SECRET_BAG_PATHS:
        cursor: Any = bags
        for part in path[:-1]:
            if not isinstance(cursor, dict):
                cursor = None
                break
            cursor = cursor.get(part) if cursor is not None else None
        if isinstance(cursor, dict) and path[-1] in cursor:
            leaf = cursor[path[-1]]
            if secret_is_present(leaf):
                cursor[path[-1]] = REDACTED_PLACEHOLDER
