"""Tests for services.agents.envelope (the app <-> agent wire format)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from core.secret_policy import MIN_AGENT_SECRET_LENGTH
from services.agents.envelope import (
    PROTOCOL_VERSION,
    EnvelopeError,
    EnvelopeExpiredError,
    EnvelopePayloadError,
    derive_http_token,
    open_envelope,
    seal,
)

SECRET = "s" * MIN_AGENT_SECRET_LENGTH
OTHER_SECRET = "t" * MIN_AGENT_SECRET_LENGTH
AGENT = "agent-1"
NOW = 1_700_000_000
VECTORS = Path(__file__).parent / "fixtures" / "agent_envelope_vectors.json"


def _seal(payload: dict | None = None, **overrides):
    kwargs = {
        "secret": SECRET,
        "agent_id": AGENT,
        "command_id": "cmd-1",
        "direction": "request",
        "ttl_seconds": 30,
        "now": NOW,
    }
    kwargs.update(overrides)
    return seal(payload if payload is not None else {"handler": "echo"}, **kwargs)


def _open(envelope: dict, **overrides):
    kwargs = {
        "secret": SECRET,
        "expected_agent_id": AGENT,
        "expected_direction": "request",
        "expected_command_id": "cmd-1",
        "now": NOW,
    }
    kwargs.update(overrides)
    return open_envelope(envelope, **kwargs)


class RoundTripTests(unittest.TestCase):
    def test_round_trip_returns_payload_and_header(self) -> None:
        envelope = _seal({"handler": "echo", "inputs": {"a": 1}})
        opened = _open(envelope)
        self.assertEqual(opened.payload, {"handler": "echo", "inputs": {"a": 1}})
        self.assertEqual(opened.agent_id, AGENT)
        self.assertEqual(opened.command_id, "cmd-1")
        self.assertEqual(opened.direction, "request")
        self.assertEqual(opened.issued_at, NOW)
        self.assertEqual(opened.expires_at, NOW + 30)

    def test_envelope_is_json_serialisable_and_hides_payload(self) -> None:
        envelope = _seal({"password": "hunter2-very-secret"})
        wire = json.dumps(envelope)
        self.assertNotIn("hunter2", wire)
        self.assertEqual(envelope["v"], PROTOCOL_VERSION)

    def test_nonce_differs_per_message(self) -> None:
        self.assertNotEqual(_seal()["nonce"], _seal()["nonce"])


class RejectionTests(unittest.TestCase):
    def test_wrong_secret(self) -> None:
        with self.assertRaises(EnvelopeError):
            _open(_seal(), secret=OTHER_SECRET)

    def test_tampered_ciphertext(self) -> None:
        envelope = _seal()
        ct = envelope["ct"]
        envelope["ct"] = ("A" if ct[0] != "A" else "B") + ct[1:]
        with self.assertRaises(EnvelopeError):
            _open(envelope)

    def test_tampered_header_fields_are_authenticated(self) -> None:
        for field, value in (("command_id", "cmd-2"), ("agent_id", "evil"), ("exp", NOW + 9999)):
            with self.subTest(field=field):
                envelope = _seal()
                envelope[field] = value
                with self.assertRaises(EnvelopeError):
                    _open(envelope, expected_agent_id=value if field == "agent_id" else AGENT,
                          expected_command_id=value if field == "command_id" else "cmd-1")

    def test_response_cannot_be_replayed_as_request(self) -> None:
        response = _seal(direction="response")
        with self.assertRaises(EnvelopeError):
            _open(response, expected_direction="request")
        # even if the header direction is rewritten, the per-direction key differs
        response["direction"] = "request"
        with self.assertRaises(EnvelopeError):
            _open(response, expected_direction="request")

    def test_wrong_agent_or_command(self) -> None:
        with self.assertRaises(EnvelopeError):
            _open(_seal(), expected_agent_id="other")
        with self.assertRaises(EnvelopeError):
            _open(_seal(), expected_command_id="cmd-2")

    def test_expired(self) -> None:
        with self.assertRaises(EnvelopeExpiredError):
            _open(_seal(), now=NOW + 31)

    def test_issued_in_the_future_beyond_skew(self) -> None:
        with self.assertRaises(EnvelopeError):
            _open(_seal(now=NOW + 120, ttl_seconds=600), now=NOW)

    def test_unknown_version_and_malformed(self) -> None:
        envelope = _seal()
        envelope["v"] = 99
        with self.assertRaises(EnvelopeError):
            _open(envelope)
        with self.assertRaises(EnvelopeError):
            _open({"v": PROTOCOL_VERSION})
        with self.assertRaises(EnvelopeError):
            _open("not a dict")  # type: ignore[arg-type]

    def test_error_message_never_contains_secret(self) -> None:
        try:
            _open(_seal(), secret=OTHER_SECRET)
        except EnvelopeError as exc:
            self.assertNotIn(SECRET, str(exc))
            self.assertNotIn(OTHER_SECRET, str(exc))

    def test_short_secret_rejected_on_both_sides(self) -> None:
        with self.assertRaises(EnvelopeError):
            _seal(secret="short")
        with self.assertRaises(EnvelopeError):
            _open(_seal(), secret="short")

    def test_non_json_payload_rejected(self) -> None:
        with self.assertRaises(EnvelopeError):
            _seal({"x": object()})


class PayloadErrorTests(unittest.TestCase):
    """A payload that decrypts but is unusable is not an authentication failure."""

    def _envelope_with_plaintext(self, plaintext: bytes) -> dict:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        from services.agents import envelope as mod

        header = {
            "v": PROTOCOL_VERSION, "agent_id": AGENT, "command_id": "cmd-1",
            "direction": "request", "iat": NOW, "exp": NOW + 30,
        }
        nonce = bytes(12)
        key = mod._message_key(SECRET, "request", AGENT)
        ct = AESGCM(key).encrypt(nonce, plaintext, mod._aad(header))
        return {**header, "nonce": mod._b64e(nonce), "ct": mod._b64e(ct)}

    def test_invalid_json_non_object_and_absurd_nesting(self) -> None:
        for plaintext in (b"not json", b"[1, 2]", b"[" * 100_000 + b"]" * 100_000):
            with self.subTest(size=len(plaintext)), self.assertRaises(EnvelopePayloadError):
                _open(self._envelope_with_plaintext(plaintext))

    def test_a_payload_error_is_still_an_envelope_error_but_a_tag_failure_is_not_one(self) -> None:
        with self.assertRaises(EnvelopeError):
            _open(self._envelope_with_plaintext(b"not json"))
        try:
            _open(_seal(), secret=OTHER_SECRET)
        except EnvelopePayloadError:
            self.fail("a wrong secret must not look like a payload problem")
        except EnvelopeError:
            pass


class HttpTokenTests(unittest.TestCase):
    def test_token_is_stable_and_secret_and_agent_specific(self) -> None:
        token = derive_http_token(SECRET, AGENT)
        self.assertEqual(token, derive_http_token(SECRET, AGENT))
        self.assertNotEqual(token, derive_http_token(OTHER_SECRET, AGENT))
        self.assertNotEqual(token, derive_http_token(SECRET, "agent-2"))
        self.assertNotIn(SECRET, token)


class VectorTests(unittest.TestCase):
    """The same vectors run in agent/<name>/tests: proves both copies are byte-compatible."""

    def test_vectors_open(self) -> None:
        data = json.loads(VECTORS.read_text())
        for vector in data["vectors"]:
            with self.subTest(vector["name"]):
                opened = open_envelope(
                    vector["envelope"],
                    secret=data["secret"],
                    expected_agent_id=vector["envelope"]["agent_id"],
                    expected_direction=vector["envelope"]["direction"],
                    expected_command_id=vector["envelope"]["command_id"],
                    now=vector["now"],
                )
                self.assertEqual(opened.payload, vector["payload"])
        self.assertEqual(
            derive_http_token(data["secret"], data["http_token_agent_id"]), data["http_token"]
        )


if __name__ == "__main__":
    unittest.main()
