"""Best-effort secret redaction for text sent to an LLM (doc/ai_integration/AI_ASSISTANT.md §4.3).

Secrets are replaced by *restorable tokens* (``__SECRET_1__``) rather than a fixed marker, so a
model that edits around a redacted line can round-trip it: ``restore`` puts the original value
back into whatever the model proposes. This is risk reduction, not a guarantee.

Design rules: only the secret value is replaced (the surrounding config line stays, so the model
can still reason about it); Jinja expressions (``{{ }}``, ``{% %}``, ``{# #}``) are never touched;
false positives are acceptable, false negatives are the risk; every pattern is line-bounded so
there is no catastrophic backtracking.
"""

from __future__ import annotations

import json
import re
from typing import Any

from services.workflow_context.secret_fields import (
    is_sealed_secret,
    is_secret_key_name,
    redact_secrets_in_data,
)

PLACEHOLDER_MARKER = "***REDACTED***"

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
    (
        "private-key",
        re.compile(
            r"(?P<s>-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----)",
            re.DOTALL,
        ),
    ),
    ("enable", re.compile(rf"\benable[ \t]+(?:secret|password){_TYPE}[ \t]+{_V}", _FLAGS)),
    (
        "username",
        re.compile(
            rf"\busername[ \t]+\S+[ \t]+(?:[^\n]*?[ \t])?(?:password|secret){_TYPE}[ \t]+{_V}",
            _FLAGS,
        ),
    ),
    (
        "aaa-server-key",
        re.compile(
            rf"\b(?:tacacs|radius)-server\b[^\n]*?[ \t]key{_TYPE}[ \t]+{_V}",
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
    ("auth-header", re.compile(r"\b(?:Bearer|Basic)[ \t]+(?P<s>[A-Za-z0-9._~+/=-]{8,})", _FLAGS)),
)

_JINJA_SPAN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_TOKEN = re.compile(r"__SECRET_(\d+)__")


def _jinja_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _JINJA_SPAN.finditer(text)]


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < span_end and end > span_start for span_start, span_end in spans)


class SecretRelocationError(ValueError):
    """The model echoed a token under a different field than the one the secret came from."""

    def __init__(self, token: str, key: str | None) -> None:
        super().__init__(
            f"{token} stands for a secret that belongs to another field and cannot be used "
            f"in '{key or 'this position'}'"
        )
        self.token = token


class Redactor:
    """One instance per request: the token table is request-scoped, never shared or stored."""

    def __init__(self) -> None:
        self._token_by_secret: dict[str, str] = {}
        self._secret_by_token: dict[str, str] = {}
        # Tokens standing in for a whole non-string value (e.g. a sealed secret envelope).
        self._object_by_token: dict[str, Any] = {}
        # Dict keys a token was found under by ``tokenize_data``. ``restore_data`` puts a token back
        # only under one of these, so a model cannot move a secret into a field the user never saw
        # it in (e.g. a chat message). Tokens made outside ``tokenize_data`` are unrestricted.
        self._origin_keys: dict[str, set[str]] = {}
        self._active_key: str | None = None

    def _token_for(self, secret: str) -> str:
        token = self._token_by_secret.get(secret)
        if token is None:
            token = f"__SECRET_{len(self._token_by_secret) + 1}__"
            self._token_by_secret[secret] = token
            self._secret_by_token[token] = secret
        if self._active_key is not None:
            self._origin_keys.setdefault(token, set()).add(self._active_key)
        return token

    def redact(self, text: str) -> str:
        for _name, pattern in _PATTERNS:
            spans = _jinja_spans(text)

            def replace(match: re.Match[str], spans: list[tuple[int, int]] = spans) -> str:
                start, end = match.span("s")
                if _overlaps(start, end, spans):
                    return match.group(0)
                value = match.group("s")
                if _TOKEN.fullmatch(value):
                    return match.group(0)
                offset = match.start()
                token = self._token_for(value)
                whole = match.group(0)
                return whole[: start - offset] + token + whole[end - offset :]

            text = pattern.sub(replace, text)
        return text

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

    def tokenize_data(self, data: Any) -> Any:
        """Restorable structured redaction for editable configs (workflow steps).

        Values under secret-named keys and sealed envelopes become tokens (``restore_data`` puts
        the originals back), and every other string leaf gets the text redaction. Unlike
        ``redact_data`` nothing becomes a literal ``***REDACTED***``, so a model that echoes the
        structure back cannot overwrite a real secret with a placeholder.
        """
        return self._tokenize(data)

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

    def _check_origin(self, token: str, key: str | None) -> None:
        origins = self._origin_keys.get(token)
        if origins and key not in origins:
            raise SecretRelocationError(token, key)

    def restore_data(self, data: Any, _key: str | None = None) -> Any:
        """Inverse of ``tokenize_data`` (also restores text tokens inside strings).

        Raises ``SecretRelocationError`` when a token appears under a key it did not come from.
        """
        if isinstance(data, str):
            if data in self._object_by_token:
                self._check_origin(data, _key)
                return self._object_by_token[data]
            return self.restore(data, key=_key, check_origin=True)
        if isinstance(data, dict):
            return {
                k: self.restore_data(item, k if isinstance(k, str) else None)
                for k, item in data.items()
            }
        if isinstance(data, list):
            return [self.restore_data(item, _key) for item in data]
        return data

    def restore(self, text: str, *, key: str | None = None, check_origin: bool = False) -> str:
        """Put original secrets back. Unknown tokens are left as they are."""

        def put_back(match: re.Match[str]) -> str:
            token = match.group(0)
            if check_origin:
                self._check_origin(token, key)
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
