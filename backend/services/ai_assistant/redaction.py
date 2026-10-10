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

import re
from typing import Any

from services.workflow_context.secret_fields import redact_secrets_in_data

PLACEHOLDER_MARKER = "***REDACTED***"

_FLAGS = re.IGNORECASE | re.MULTILINE
# The secret value: one non-space token that does not start a Jinja expression.
_V = r"(?P<s>(?!\{)\S+)"
# A Cisco secret *type* is a single digit followed by whitespace; matching it possessively means
# "enable secret 9 {{ x }}" cannot backtrack into treating the type digit as the secret.
_TYPE = r"(?:[ \t]+[0-9](?=[ \t]))?+"
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
    ("enable", re.compile(rf"^[ \t]*enable[ \t]+(?:secret|password){_TYPE}[ \t]+{_V}", _FLAGS)),
    (
        "username",
        re.compile(
            rf"^[ \t]*username[ \t]+\S+[ \t]+(?:[^\n]*?[ \t])?(?:password|secret){_TYPE}[ \t]+{_V}",
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


class Redactor:
    """One instance per request: the token table is request-scoped, never shared or stored."""

    def __init__(self) -> None:
        self._token_by_secret: dict[str, str] = {}
        self._secret_by_token: dict[str, str] = {}

    def _token_for(self, secret: str) -> str:
        token = self._token_by_secret.get(secret)
        if token is None:
            token = f"__SECRET_{len(self._token_by_secret) + 1}__"
            self._token_by_secret[secret] = token
            self._secret_by_token[token] = secret
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

    def restore(self, text: str) -> str:
        """Put original secrets back. Unknown tokens are left as they are."""
        return _TOKEN.sub(lambda m: self._secret_by_token.get(m.group(0), m.group(0)), text)

    @staticmethod
    def contains_unresolved_placeholder(text: str) -> bool:
        """The structured redactor's literal marker must never be persisted as a real value."""
        return PLACEHOLDER_MARKER in text
