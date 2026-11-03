"""The signed confirmation token for a proposed device command (doc/AI_TOOL_CHAIN.md §13.2)."""

from __future__ import annotations

import base64
import json

import pytest

from core.config import settings
from services.ai_assistant import device_token as dt


@pytest.fixture(autouse=True)
def _secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "secret_key", "k" * 40)


def _issue(**overrides):
    base = {
        "user_id": 7,
        "source_id": "nb1",
        "device_id": "dev-uuid",
        "device_name": "LAB",
        "host": "10.1.2.3",
        "commands": ["show running-config"],
        "now": 1000.0,
    }
    base.update(overrides)
    return dt.issue_token(**base)


def test_round_trip_returns_what_was_proposed() -> None:
    token, expires_at = _issue(commands=["show running-config", "show version"])

    grant = dt.verify_token(token, user_id=7, now=1001.0)

    assert grant == dt.DeviceCommandGrant(
        user_id=7,
        source_id="nb1",
        device_id="dev-uuid",
        device_name="LAB",
        host="10.1.2.3",
        commands=("show running-config", "show version"),
        expires_at=expires_at,
    )
    assert expires_at == 1000.0 + dt.TOKEN_TTL_SECONDS
    assert dt.TOKEN_TTL_SECONDS == 600  # about ten minutes (doc/AI_TOOL_CHAIN.md §29)


def test_the_token_is_bound_to_the_user() -> None:
    token, _ = _issue()

    with pytest.raises(dt.InvalidTokenError):
        dt.verify_token(token, user_id=8, now=1001.0)


def test_an_expired_token_is_refused_and_the_last_second_is_not() -> None:
    token, expires_at = _issue()

    assert dt.verify_token(token, user_id=7, now=expires_at - 1)
    with pytest.raises(dt.InvalidTokenError):
        dt.verify_token(token, user_id=7, now=expires_at)


def _resign(payload: dict) -> str:
    """A token with a changed payload but the signature of the original."""
    token, _ = _issue()
    _body, signature = token.split(".")
    new_body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode()
    return f"{new_body}.{signature}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("d", "other-device"),
        ("n", "OTHER"),
        ("h", "10.9.9.9"),
        ("s", "nb2"),
        ("u", 8),
        ("c", ["show running-config", "show version"]),
        ("c", ["reload"]),
        ("p", "genie"),
        ("x", 10**12),
    ],
)
def test_changing_any_field_breaks_the_signature(field: str, value) -> None:
    token, _ = _issue()
    body = token.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(body))
    payload[field] = value

    with pytest.raises(dt.InvalidTokenError):
        dt.verify_token(_resign(payload), user_id=7, now=1001.0)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "abc",
        "a.b",
        "a.b.c",
        ".",
        "!!!.???",
        "e30=.e30=",
        None,
        5,
        "x" * 100_000,
        "é.é",
        "e30=.é",
        "é.e30=",
    ],
)
def test_garbage_is_refused(token) -> None:
    with pytest.raises(dt.InvalidTokenError):
        dt.verify_token(token, user_id=7, now=1001.0)


def test_a_token_signed_with_another_secret_is_refused(monkeypatch) -> None:
    token, _ = _issue()
    monkeypatch.setattr(settings, "secret_key", "z" * 40)

    with pytest.raises(dt.InvalidTokenError):
        dt.verify_token(token, user_id=7, now=1001.0)


def test_the_signature_is_compared_in_constant_time(monkeypatch) -> None:
    calls: list[tuple] = []
    real = dt.hmac.compare_digest

    def spy(a, b):
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(dt.hmac, "compare_digest", spy)
    token, _ = _issue()

    dt.verify_token(token, user_id=7, now=1001.0)

    assert len(calls) == 1


def test_the_token_does_not_contain_the_secret_or_a_credential() -> None:
    token, _ = _issue()

    assert "k" * 40 not in token
    assert "credential" not in base64.urlsafe_b64decode(token.split(".")[0]).decode()


def test_the_parser_round_trips_and_defaults_to_none() -> None:
    plain, _ = _issue()
    parsed, _ = _issue(parser="textfsm")

    assert dt.verify_token(plain, user_id=7, now=1001.0).parser == "none"
    assert dt.verify_token(parsed, user_id=7, now=1001.0).parser == "textfsm"


def test_a_signed_token_with_an_unknown_parser_is_refused(monkeypatch) -> None:
    with pytest.raises(ValueError):
        _issue(parser="regex")
    token, _ = _issue()
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[0]))
    payload["p"] = "regex"
    body = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).decode()
    forged = f"{body}.{base64.urlsafe_b64encode(dt._sign(body.encode())).decode()}"

    with pytest.raises(dt.InvalidTokenError):
        dt.verify_token(forged, user_id=7, now=1001.0)
