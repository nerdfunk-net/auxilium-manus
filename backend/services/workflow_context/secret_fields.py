"""Seal, unwrap, and redact sensitive workflow attribute values.

TACACS shared secrets (and similar) may ride in ``DeviceContext.attribute_bags``
for in-run use, but must never appear as cleartext in persisted step results
(``WorkflowStepResult.output``), log-attributes dumps, or INFO logs.

Data-flow:

- **Sealed** (at rest in bags / in-memory between steps): a Fernet envelope
  produced by :func:`seal_secret`, reusing the same key material as
  credential-table encryption (``core.crypto.EncryptionService``).
- **Exported** (DB step output, log-attributes files, log-message metadata,
  any run API): always the literal ``***REDACTED***`` placeholder via
  :func:`redact_secrets_in_data` — never even ciphertext.
- **Consumed** (attribute resolution, Jinja namespace, ISE update payloads):
  unwrapped to cleartext only in process memory for the duration of the call,
  via :func:`unwrap_secret`.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from core.crypto import EncryptionService

SEALED_MARKER = "__am_sealed__"
REDACTED_PLACEHOLDER = "***REDACTED***"

# Shorter values (an "up", a port) would redact ordinary text and add no protection.
MIN_TRACKED_SECRET_LENGTH = 8

# Cleartext secrets seen while one run segment executes (W6). None outside a run. The set is
# mutable and created once per segment, so sibling tasks (asyncio.gather) and worker threads
# (asyncio.to_thread), which copy the context, all share it.
_RUN_SECRETS: ContextVar[set[str] | None] = ContextVar("run_secrets", default=None)


@contextmanager
def run_secret_scope():
    """Start (or join) a per-run-segment secret registry."""
    if _RUN_SECRETS.get() is not None:
        yield
        return
    token = _RUN_SECRETS.set(set())
    try:
        yield
    finally:
        _RUN_SECRETS.reset(token)


def with_run_secret_scope[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Decorator form of :func:`run_secret_scope` for the step runner's async entry points."""

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with run_secret_scope():
            return await fn(*args, **kwargs)

    return wrapper


def register_secret_value(value: str | None) -> None:
    """Remember a cleartext secret so later redaction can scrub it from free text."""
    registry = _RUN_SECRETS.get()
    if registry is not None and value and len(value) >= MIN_TRACKED_SECRET_LENGTH:
        registry.add(value)

# Dotted paths relative to a device's attribute_bags that are treated as
# secret-valued regardless of whether the leaf is sealed or (legacy) plain
# cleartext.
SECRET_BAG_PATHS: tuple[tuple[str, ...], ...] = (
    ("tacacs", "shared_secret"),
    ("ise", "tacacsSettings", "sharedSecret"),
    ("pyats_testbed", "password"),
)

# Dict keys whose lowercase (dash/underscore-normalized) name marks the value
# as secret, anywhere in the structure — not just under attribute_bags. This
# catches e.g. command-output JSON that happens to carry a "password" field.
_SECRET_KEY_NAMES = frozenset(
    {
        "password",
        "secret",
        "token",
        "community",
        "shared_secret",
        "sharedsecret",
        "passphrase",
        "api_key",
        "apikey",
        "enable_secret",
        "snmp_community",
    }
)


def _key_is_secret_name(key: str) -> bool:
    lowered = key.replace("-", "_").lower()
    if lowered in _SECRET_KEY_NAMES:
        return True
    return lowered.endswith(("_password", "_secret", "_token", "_passphrase"))


def is_secret_key_name(key: str) -> bool:
    """Public form of the key-name rule: does this dict key name hold a secret value?"""
    return _key_is_secret_name(key)


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
        cleartext = svc.decrypt(str(value["ct"]).encode("ascii"))
        register_secret_value(cleartext)
        return cleartext
    if isinstance(value, str):
        stripped = value.strip()
        register_secret_value(stripped)
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

    3. Inside a run segment (:func:`run_secret_scope`), every cleartext secret that
       was unwrapped (:func:`unwrap_secret`) or resolved from a credential during
       the run is also scrubbed, by exact match, from string leaves (W6).

    Limitation: a secret that never passed through :func:`unwrap_secret` or a
    credential decrypt (e.g. typed into a template by the author) is unknown to
    the redactor, and values shorter than ``MIN_TRACKED_SECRET_LENGTH`` are not
    tracked. Steps that resolve secret values must still not copy them into
    free text — see ``doc/WORKFLOW-STEPS.md``.
    """
    cloned = deepcopy(data)
    _redact_inplace(cloned)
    known = _RUN_SECRETS.get()
    if known:
        # Longest first, so a secret that contains another is scrubbed whole.
        cloned = _scrub_known_values(cloned, sorted(known, key=len, reverse=True))
    return cloned


def contains_sealed_secret(data: Any) -> bool:
    """True when a sealed envelope occurs anywhere inside *data* (dicts and lists are walked)."""
    if is_sealed_secret(data):
        return True
    if isinstance(data, dict):
        return any(contains_sealed_secret(value) for value in data.values())
    if isinstance(data, list):
        return any(contains_sealed_secret(item) for item in data)
    return False


def unwrap_all_secrets(data: Any, *, encryption: EncryptionService | None = None) -> Any:
    """Deep copy of *data* with every sealed envelope replaced by its cleartext.

    Only for sinks that the operator explicitly accepted as secret stores
    (``store-in-db`` with ``allow_secret_storage``). Raises ``ValueError`` when an envelope
    cannot be decrypted, like :func:`unwrap_secret`.
    """
    if is_sealed_secret(data):
        return unwrap_secret(data, encryption=encryption)
    if isinstance(data, dict):
        return {
            key: unwrap_all_secrets(value, encryption=encryption) for key, value in data.items()
        }
    if isinstance(data, list):
        return [unwrap_all_secrets(item, encryption=encryption) for item in data]
    return data


def _redact_inplace(node: Any) -> None:
    if isinstance(node, dict):
        bags = node.get("attribute_bags")
        if isinstance(bags, dict):
            _redact_bag_paths(bags)
        for key, value in list(node.items()):
            if is_sealed_secret(value):
                node[key] = REDACTED_PLACEHOLDER
            elif isinstance(value, str) and _key_is_secret_name(key):
                node[key] = REDACTED_PLACEHOLDER
            else:
                _redact_inplace(value)
    elif isinstance(node, list):
        for item in node:
            _redact_inplace(item)


def scrub_known_secrets(data: Any) -> Any:
    """Replace known cleartext secrets in string leaves of *data* (content scrub only).

    Unlike :func:`redact_secrets_in_data` this leaves sealed envelopes and secret-named keys
    alone, so the result is still usable as a working context (e.g. a fan-out child's result
    that the parent merges). Returns *data* unchanged outside a run scope."""
    known = _RUN_SECRETS.get()
    if not known:
        return data
    return _scrub_known_values(data, sorted(known, key=len, reverse=True))


def _scrub_string(text: str, secrets: list[str]) -> str:
    """Replace every occurrence of any secret, merging overlapping matches so no tail of an
    overlapping pair (``abcdefgh`` / ``defghijk`` in ``abcdefghijk``) is left behind."""
    spans: list[tuple[int, int]] = []
    for secret in secrets:
        start = text.find(secret)
        while start != -1:
            spans.append((start, start + len(secret)))
            start = text.find(secret, start + 1)
    if not spans:
        return text
    spans.sort()
    merged = [spans[0]]
    for begin, end in spans[1:]:
        last_begin, last_end = merged[-1]
        if begin <= last_end:
            merged[-1] = (last_begin, max(last_end, end))
        else:
            merged.append((begin, end))
    pieces: list[str] = []
    cursor = 0
    for begin, end in merged:
        pieces.append(text[cursor:begin])
        pieces.append(REDACTED_PLACEHOLDER)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def _scrub_known_values(node: Any, secrets: list[str]) -> Any:
    """Replace every exact occurrence of a known cleartext secret in string leaves (W6)."""
    if isinstance(node, str):
        return _scrub_string(node, secrets)
    if isinstance(node, dict):
        return {key: _scrub_known_values(value, secrets) for key, value in node.items()}
    if isinstance(node, list):
        return [_scrub_known_values(item, secrets) for item in node]
    return node


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
