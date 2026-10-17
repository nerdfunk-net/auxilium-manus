"""Best-effort secret redaction for text sent to an LLM (doc/ai_integration/AI_ASSISTANT.md §4.3).

Secrets are replaced by *restorable tokens* (``__SECRET_1__``) rather than a fixed marker, so a
model that edits around a redacted line can round-trip it: ``restore`` puts the original value
back into whatever the model proposes. This is risk reduction, not a guarantee.

Design rules: only the secret value is replaced (the surrounding config line stays, so the model
can still reason about it); Jinja expressions (``{{ }}``, ``{% %}``, ``{# #}``) are never touched;
false positives are acceptable, false negatives are the risk. Work is linear in the input: Jinja
spans and PEM blocks are found once per text with ``str.find`` (never a backtracking regex), every
other pattern is line-bounded with a bounded look-ahead, and one ``Redactor`` refuses to redact
more than ``MAX_REDACT_CHARS_PER_REQUEST`` characters (S5-01).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from services.workflow_context.secret_fields import (
    is_sealed_secret,
    is_secret_key_name,
    redact_secrets_in_data,
)

PLACEHOLDER_MARKER = "***REDACTED***"

# Exact-match tracking ignores values shorter than this (too many false positives).
MIN_TRACKED_SECRET_LENGTH = 8

# Sum of the characters passed to ``redact`` over the life of one Redactor (one request).
MAX_REDACT_CHARS_PER_REQUEST = 1_000_000
# A secret keyword sits within this many characters of its anchor on the same line.
_LINE_SCAN = 200
# Private-use code points that stand in for a Jinja span while the patterns run.
_SENTINEL_OPEN = "\ue000"
_SENTINEL_CLOSE = "\ue001"
_JINJA_PAIRS = (("{{", "}}"), ("{%", "%}"), ("{#", "#}"))
_PEM_BEGIN, _PEM_END = "-----BEGIN ", "PRIVATE KEY-----"


class RedactionBudgetExceeded(ValueError):
    """The request would redact more text than ``MAX_REDACT_CHARS_PER_REQUEST``."""


_FLAGS = re.IGNORECASE | re.MULTILINE
# The secret value: one non-space token that does not start a Jinja expression.
_V = r"(?P<s>(?!\{)\S+)"
# A secret *type* is a single digit (Cisco) or a hash name (Arista) followed by whitespace;
# matching it possessively means "enable secret 9 {{ x }}" cannot backtrack into treating the
# type digit as the secret.
_TYPE = r"(?:[ \t]+(?:[0-9]|sha512|sha256)(?=[ \t]))?+"
# A key/id number (possibly several digits), same possessive rule.
_NUM = r"(?:[ \t]+\d+(?=[ \t]))?+"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("enable", re.compile(rf"\benable[ \t]+(?:secret|password){_TYPE}[ \t]+{_V}", _FLAGS)),
    (
        "username",
        re.compile(
            rf"\busername[ \t]+\S+[ \t]+(?:[^\n]{{0,{_LINE_SCAN}}}?[ \t])?"
            rf"(?:password|secret){_TYPE}[ \t]+{_V}",
            _FLAGS,
        ),
    ),
    (
        "aaa-server-key",
        re.compile(
            rf"\b(?:tacacs|radius)-server\b[^\n]{{0,{_LINE_SCAN}}}?[ \t]key{_TYPE}[ \t]+{_V}",
            _FLAGS,
        ),
    ),
    ("server-block-key", re.compile(rf"^[ \t]+key[ \t]+\d[ \t]+{_V}", _FLAGS)),
    ("key-string", re.compile(rf"\bkey-string(?:[ \t]+\d)?[ \t]+{_V}", _FLAGS)),
    ("snmp-community", re.compile(rf"\bsnmp-server[ \t]+community[ \t]+{_V}", _FLAGS)),
    ("snmp-v3-auth", re.compile(rf"\bauth[ \t]+(?:md5|sha\w*)[ \t]+{_V}", _FLAGS)),
    ("snmp-v3-priv", re.compile(rf"\bpriv[ \t]+(?:des|3des|aes){_NUM}[ \t]+{_V}", _FLAGS)),
    (
        "message-digest-key",
        re.compile(rf"\bmessage-digest-key[ \t]+\d+[ \t]+md5(?:[ \t]+\d)?[ \t]+{_V}", _FLAGS),
    ),
    (
        "authentication-key",
        re.compile(
            rf"\bauthentication-key{_NUM}(?:[ \t]+md5)?{_TYPE}[ \t]+{_V}",
            _FLAGS,
        ),
    ),
    (
        "hsrp-authentication",
        re.compile(
            r"\bstandby[ \t]+\d+[ \t]+authentication[ \t]+"
            rf"(?:md5[ \t]+key-string(?:[ \t]+\d)?[ \t]+|text[ \t]+)?{_V}",
            _FLAGS,
        ),
    ),
    ("isakmp-key", re.compile(rf"\bisakmp[ \t]+key{_TYPE}[ \t]+{_V}", _FLAGS)),
    (
        "neighbor-password",
        re.compile(rf"\bneighbor[ \t]+\S+[ \t]+password{_TYPE}[ \t]+{_V}", _FLAGS),
    ),
    (
        "pre-shared-key",
        re.compile(
            r"\bpre-shared-key(?:[ \t]+(?:local|remote|hexadecimal|ascii-text|ascii))*"
            rf"{_TYPE}[ \t]+\"?(?P<s>(?![{{\"])[^\s\";]+)",
            _FLAGS,
        ),
    ),
    (
        "ppp-password",
        re.compile(rf"\bppp[ \t]+(?:chap|pap)[ \t]+password{_TYPE}[ \t]+{_V}", _FLAGS),
    ),
    ("wpa-psk", re.compile(rf"\bwpa-psk(?:[ \t]+(?:ascii|hex)){{0,1}}{_TYPE}[ \t]+{_V}", _FLAGS)),
    (
        "quoted-secret",
        re.compile(
            r"\b(?:encrypted-password|authentication-key|simple-password|secret|md5)[ \t]+"
            r"\"(?P<s>(?![{}%])[^\"\n]+)\"",
            _FLAGS,
        ),
    ),
    ("junos-community", re.compile(r"\bcommunity[ \t]+(?P<s>[A-Za-z0-9_.-]+)[ \t]*\{", _FLAGS)),
    ("line-password", re.compile(rf"^[ \t]*password(?:[ \t]+\d)?[ \t]+{_V}", _FLAGS)),
    (
        "assignment",
        re.compile(
            r"\b(?:password|passwd|secret|token|api[_-]?key|passphrase)\b[ \t]*[:=][ \t]*[\"']?"
            r"(?P<s>(?![{}%])[^\s\"']+)",
            _FLAGS,
        ),
    ),
    (
        "snmp-host",
        re.compile(
            rf"\bsnmp-server[ \t]+host[ \t]+\S+[ \t]+(?:[^\n]{{0,60}}?[ \t])?"
            rf"version[ \t]+(?:1|2c)[ \t]+{_V}",
            _FLAGS,
        ),
    ),
    (
        "ftp-http-password",
        re.compile(rf"\bip[ \t]+(?:ftp|http[ \t]+client)[ \t]+password{_TYPE}[ \t]+{_V}", _FLAGS),
    ),
    (
        "fortios-enc",
        re.compile(
            rf"\bset[ \t]+(?:psksecret|password|passwd|secret|key)[ \t]+ENC[ \t]+{_V}", _FLAGS
        ),
    ),
    ("junos-set-community", re.compile(rf"\bset[ \t]+snmp[ \t]+community[ \t]+{_V}", _FLAGS)),
    ("aruba-mgmt-user", re.compile(rf"\bmgmt-user[ \t]+\S+[ \t]+\S+[ \t]+{_V}", _FLAGS)),
    ("set-key", re.compile(rf"\bset-key[ \t]+(?:ascii|hex)[ \t]+\d[ \t]+{_V}", _FLAGS)),
    (
        "env-secret-name",
        re.compile(
            r"\b[A-Za-z0-9_]{0,60}(?:_key|_pw|_pass|_passwd|_psk|_community|_secret|_password)"
            r"[ \t]*[:=][ \t]*[\"']?(?P<s>(?![{}%])[^\s\"']+)",
            _FLAGS,
        ),
    ),
    ("auth-header", re.compile(r"\b(?:Bearer|Basic)[ \t]+(?P<s>[A-Za-z0-9._~+/=-]{8,})", _FLAGS)),
)

_TOKEN = re.compile(r"__SECRET_(\d+)__")
_UNMASK = re.compile(f"{_SENTINEL_OPEN}(\\d+){_SENTINEL_CLOSE}")


def _jinja_spans(text: str) -> list[tuple[int, int]]:
    """All ``{{ }}`` / ``{% %}`` / ``{# #}`` spans in one linear pass.

    ``str.find`` only: an opener whose closer does not exist ends the search for that kind
    (``exhausted``), so ``"{{ " * n`` costs O(n), not O(n^2)."""
    spans: list[tuple[int, int]] = []
    exhausted: set[str] = set()
    cursor = 0
    while True:
        best: tuple[int, str, str] | None = None
        for opener, closer in _JINJA_PAIRS:
            if opener in exhausted:
                continue
            position = text.find(opener, cursor)
            if position == -1:
                exhausted.add(opener)
            elif best is None or position < best[0]:
                best = (position, opener, closer)
        if best is None:
            return spans
        start, opener, closer = best
        end = text.find(closer, start + 2)
        if end == -1:
            exhausted.add(opener)  # no closer anywhere after: never look for this opener again
            continue
        spans.append((start, end + 2))
        cursor = end + 2


def _mask(text: str) -> tuple[str, list[str]]:
    """Replace each Jinja span by a private-use placeholder so no pattern can match inside one."""
    spans = _jinja_spans(text)
    if not spans:
        return text, []
    pieces: list[str] = []
    saved: list[str] = []
    cursor = 0
    for index, (start, end) in enumerate(spans):
        pieces.append(text[cursor:start])
        pieces.append(f"{_SENTINEL_OPEN}{index}{_SENTINEL_CLOSE}")
        saved.append(text[start:end])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), saved


def _unmask(text: str, saved: list[str]) -> str:
    if not saved:
        return text

    def put_back(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return saved[index] if index < len(saved) else match.group(0)

    return _UNMASK.sub(put_back, text)


def _private_key_spans(text: str) -> list[tuple[int, int]]:
    """``-----BEGIN … PRIVATE KEY-----`` … ``-----END … PRIVATE KEY-----`` with ``str.find`` only.

    Once one BEGIN has no END after it, no later BEGIN has either, so the scan stops (O(n))."""
    spans: list[tuple[int, int]] = []
    cursor = 0
    while (begin := text.find(_PEM_BEGIN, cursor)) != -1:
        header_end = text.find("-----", begin + len(_PEM_BEGIN))
        if header_end == -1:
            break
        if not text[begin:header_end].endswith("PRIVATE KEY"):
            cursor = begin + len(_PEM_BEGIN)
            continue
        end_marker = text.find("-----END ", header_end)
        if end_marker == -1:
            break
        footer_end = text.find(_PEM_END, end_marker)
        if footer_end == -1:
            break
        spans.append((begin, footer_end + len(_PEM_END)))
        cursor = footer_end + len(_PEM_END)
    return spans


# Scope of the workflow's static attributes (steps use their node id).
STATIC_ATTRIBUTES_SCOPE = "static_attributes"


class SecretRelocationError(ValueError):
    """The model echoed a token under another field or step than the one the secret came from."""

    def __init__(self, token: str, key: str | None, scope: str | None = None) -> None:
        where = f"'{key or 'this position'}'" + (f" of '{scope}'" if scope else "")
        super().__init__(
            f"{token} stands for a secret that belongs to another field or step and cannot be "
            f"used in {where}"
        )
        self.token = token


class Redactor:
    """One instance per request: the token table is request-scoped, never shared or stored."""

    def __init__(self, *, max_chars: int = MAX_REDACT_CHARS_PER_REQUEST) -> None:
        self._max_chars = max_chars
        self._token_by_secret: dict[str, str] = {}
        self._secret_by_token: dict[str, str] = {}
        # Tokens standing in for a whole non-string value (e.g. a sealed secret envelope).
        self._object_by_token: dict[str, Any] = {}
        # (scope, dict key) pairs a token was found under by ``tokenize_data``; scope is the node id
        # (or STATIC_ATTRIBUTES_SCOPE). ``restore_data`` puts a token back only at one of these, so
        # a model can move a secret neither into a field the user never saw it in (e.g. a chat
        # message) nor into another step. Tokens made outside ``tokenize_data`` are unrestricted.
        self._origin_keys: dict[str, set[tuple[str | None, str]]] = {}
        self._active_key: str | None = None
        self._active_scope: str | None = None
        # Characters passed to redact() so far; bounded by MAX_REDACT_CHARS_PER_REQUEST.
        self._spent = 0
        # Exact values (longest first) replaced wherever they occur, see ``add_known_secrets``.
        self._known: list[str] = []

    def _token_for(self, secret: str) -> str:
        token = self._token_by_secret.get(secret)
        if token is None:
            token = f"__SECRET_{len(self._token_by_secret) + 1}__"
            self._token_by_secret[secret] = token
            self._secret_by_token[token] = secret
        if self._active_key is not None:
            self._origin_keys.setdefault(token, set()).add((self._active_scope, self._active_key))
        return token

    def add_known_secrets(self, values: Iterable[str]) -> None:
        """Register exact secret values (e.g. the user's resolvable credentials) so they become
        tokens wherever they occur, even bare on a line where no pattern would catch them."""
        wanted = {value for value in values if len(value) >= MIN_TRACKED_SECRET_LENGTH}
        merged = set(self._known) | wanted
        self._known = sorted(merged, key=len, reverse=True)

    def _replace(self, match: re.Match[str]) -> str:
        value = match.group("s")
        # A value that touches a masked Jinja span is a template expression, never a secret.
        if _SENTINEL_OPEN in value or _TOKEN.fullmatch(value):
            return match.group(0)
        start, end = match.span("s")
        offset = match.start()
        token = self._token_for(value)
        whole = match.group(0)
        return whole[: start - offset] + token + whole[end - offset :]

    def _redact_private_keys(self, text: str) -> str:
        spans = _private_key_spans(text)
        if not spans:
            return text
        pieces: list[str] = []
        cursor = 0
        for start, end in spans:
            pieces.append(text[cursor:start])
            pieces.append(self._token_for(text[start:end]))
            cursor = end
        pieces.append(text[cursor:])
        return "".join(pieces)

    def redact(self, text: str) -> str:
        self._spent += len(text)
        if self._spent > self._max_chars:
            raise RedactionBudgetExceeded("too much text to redact in one request")
        masked, saved = _mask(text)  # once per text, not once per pattern
        masked = self._redact_private_keys(masked)
        for value in self._known:
            if value in masked:
                masked = masked.replace(value, self._token_for(value))
        for _name, pattern in _PATTERNS:
            masked = pattern.sub(self._replace, masked)
        return _unmask(masked, saved)

    def redact_data(self, data: Any) -> Any:
        """Structured redaction (secret-named keys, sealed envelopes), then text redaction of
        every remaining string leaf. Returns a copy; the input is not mutated."""
        return self._redact_strings(redact_secrets_in_data(data))

    def _redact_strings(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return {key: self._redact_strings(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_strings(item) for item in value]
        return value

    def tokenize_data(self, data: Any, scope: str | None = None) -> Any:
        """Restorable structured redaction for editable configs (workflow steps).

        Values under secret-named keys and sealed envelopes become tokens (``restore_data`` puts
        the originals back), and every other string leaf gets the text redaction. Unlike
        ``redact_data`` nothing becomes a literal ``***REDACTED***``, so a model that echoes the
        structure back cannot overwrite a real secret with a placeholder.

        ``scope`` names the owner of ``data`` (a node id); its tokens restore only under that scope.
        """
        self._active_scope = scope
        try:
            return self._tokenize(data)
        finally:
            self._active_scope = None

    def _tokenize(self, value: Any, key: str | None = None) -> Any:
        if is_sealed_secret(value):
            return self._object_token(value, key)
        if isinstance(value, dict):
            return {k: self._tokenize_entry(k, item) for k, item in value.items()}
        if isinstance(value, list):
            return [self._tokenize(item, key) for item in value]
        if isinstance(value, str):
            return self._redact_under(value, key)
        return value

    def _tokenize_entry(self, key: Any, item: Any) -> Any:
        name = key if isinstance(key, str) else None
        if name is not None and is_secret_key_name(name):
            if isinstance(item, str) and item:
                return self._token_under(item, name)
            if isinstance(item, dict | list) and item:
                return self._object_token(item, name)
        return self._tokenize(item, name)

    def _redact_under(self, text: str, key: str | None) -> str:
        self._active_key = key
        try:
            return self.redact(text)
        finally:
            self._active_key = None

    def _token_under(self, secret: str, key: str | None) -> str:
        self._active_key = key
        try:
            return self._token_for(secret)
        finally:
            self._active_key = None

    def _object_token(self, value: Any, key: str | None = None) -> str:
        token = self._token_under(json.dumps(value, sort_keys=True, default=str), key)
        self._object_by_token.setdefault(token, value)
        return token

    def _check_origin(self, token: str, key: str | None, scope: str | None) -> None:
        origins = self._origin_keys.get(token)
        if origins and (scope, key) not in origins:
            raise SecretRelocationError(token, key, scope)

    def restore_data(self, data: Any, scope: str | None = None, _key: str | None = None) -> Any:
        """Inverse of ``tokenize_data`` (also restores text tokens inside strings).

        Raises ``SecretRelocationError`` when a token appears under a key or scope it did not
        come from.
        """
        if isinstance(data, str):
            if data in self._object_by_token:
                self._check_origin(data, _key, scope)
                return self._object_by_token[data]
            return self.restore(data, key=_key, scope=scope, check_origin=True)
        if isinstance(data, dict):
            return {
                k: self.restore_data(item, scope, k if isinstance(k, str) else None)
                for k, item in data.items()
            }
        if isinstance(data, list):
            return [self.restore_data(item, scope, _key) for item in data]
        return data

    def restore(
        self,
        text: str,
        *,
        key: str | None = None,
        scope: str | None = None,
        check_origin: bool = False,
    ) -> str:
        """Put original secrets back. Unknown tokens are left as they are."""

        def put_back(match: re.Match[str]) -> str:
            token = match.group(0)
            if check_origin:
                self._check_origin(token, key, scope)
            return self._secret_by_token.get(token, token)

        return _TOKEN.sub(put_back, text)

    @staticmethod
    def data_contains_placeholder(data: Any) -> bool:
        if isinstance(data, str):
            return PLACEHOLDER_MARKER in data
        if isinstance(data, dict):
            return any(Redactor.data_contains_placeholder(v) for v in data.values())
        if isinstance(data, list):
            return any(Redactor.data_contains_placeholder(v) for v in data)
        return False

    @staticmethod
    def contains_unresolved_placeholder(text: str) -> bool:
        """The structured redactor's literal marker must never be persisted as a real value."""
        return PLACEHOLDER_MARKER in text
