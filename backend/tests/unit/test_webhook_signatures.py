"""Constant-time git-webhook signature verification (core/webhook_signatures.py)."""

from __future__ import annotations

import hashlib
import hmac
import unittest

from core.webhook_signatures import verify_github_signature, verify_gitlab_token

SECRET = "s3cr3t-webhook-key"
BODY = b'{"ref":"refs/heads/manus/cr-42","after":"deadbeef"}'


def _github_sig(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class GithubSignatureTests(unittest.TestCase):
    def test_valid_signature_passes(self) -> None:
        self.assertTrue(verify_github_signature(SECRET, BODY, _github_sig(SECRET, BODY)))

    def test_tampered_body_fails(self) -> None:
        self.assertFalse(
            verify_github_signature(SECRET, BODY + b" ", _github_sig(SECRET, BODY))
        )

    def test_wrong_secret_fails(self) -> None:
        self.assertFalse(
            verify_github_signature(SECRET, BODY, _github_sig("other", BODY))
        )

    def test_missing_or_malformed_header_fails(self) -> None:
        self.assertFalse(verify_github_signature(SECRET, BODY, None))
        self.assertFalse(verify_github_signature(SECRET, BODY, ""))
        self.assertFalse(
            verify_github_signature(SECRET, BODY, "sha1=" + "0" * 40)
        )

    def test_empty_secret_fails(self) -> None:
        self.assertFalse(verify_github_signature("", BODY, _github_sig("", BODY)))


class GitlabTokenTests(unittest.TestCase):
    def test_exact_token_passes(self) -> None:
        self.assertTrue(verify_gitlab_token(SECRET, SECRET))

    def test_mismatch_fails(self) -> None:
        self.assertFalse(verify_gitlab_token(SECRET, SECRET + "x"))

    def test_missing_or_empty_fails(self) -> None:
        self.assertFalse(verify_gitlab_token(SECRET, None))
        self.assertFalse(verify_gitlab_token(SECRET, ""))
        self.assertFalse(verify_gitlab_token("", ""))


if __name__ == "__main__":
    unittest.main()
