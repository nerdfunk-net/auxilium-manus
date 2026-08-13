"""Unit tests for OIDC redirect_uri allow-list / state-binding policy."""

from __future__ import annotations

import unittest

from core.oidc_redirect import assert_redirect_matches_state, validate_oidc_redirect_uri


class ValidateOidcRedirectUriTests(unittest.TestCase):
    def test_development_allows_login_callback_on_localhost(self) -> None:
        result = validate_oidc_redirect_uri(
            "http://localhost:3000/login/callback",
            allowlist=[],
            environment="development",
        )
        self.assertEqual(result, "http://localhost:3000/login/callback")

    def test_development_allows_test_callback_on_127_0_0_1(self) -> None:
        result = validate_oidc_redirect_uri(
            "http://127.0.0.1:3000/login/oidc-test-callback",
            allowlist=[],
            environment="development",
        )
        self.assertEqual(result, "http://127.0.0.1:3000/login/oidc-test-callback")

    def test_development_rejects_arbitrary_host(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "https://evil.example/callback",
                allowlist=[],
                environment="development",
            )

    def test_production_requires_allowlist(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "https://manus.example.com/login/callback",
                allowlist=[],
                environment="production",
            )

    def test_production_allowlist_exact_match(self) -> None:
        result = validate_oidc_redirect_uri(
            "https://manus.example.com/login/callback",
            allowlist=["https://manus.example.com/login/callback"],
            environment="production",
        )
        self.assertEqual(result, "https://manus.example.com/login/callback")

    def test_production_allowlist_miss_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "https://other.example.com/login/callback",
                allowlist=["https://manus.example.com/login/callback"],
                environment="production",
            )

    def test_dev_tools_skips_allowlist(self) -> None:
        result = validate_oidc_redirect_uri(
            "https://manus.example.com/login/oidc-test-callback",
            allowlist=[],
            environment="production",
            dev_tools=True,
        )
        self.assertEqual(result, "https://manus.example.com/login/oidc-test-callback")

    def test_dev_tools_still_requires_http_scheme(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "ftp://manus.example.com/callback",
                allowlist=[],
                environment="production",
                dev_tools=True,
            )

    def test_rejects_embedded_credentials(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "https://user:pass@manus.example.com/login/callback",
                allowlist=["https://user:pass@manus.example.com/login/callback"],
                environment="production",
            )

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri("", allowlist=[], environment="development")


class AssertRedirectMatchesStateTests(unittest.TestCase):
    def test_matching_uris_pass(self) -> None:
        assert_redirect_matches_state(
            "https://manus.example.com/login/callback",
            "https://manus.example.com/login/callback",
        )

    def test_mismatched_uris_raise(self) -> None:
        with self.assertRaises(ValueError):
            assert_redirect_matches_state(
                "https://manus.example.com/login/callback",
                "https://evil.example/callback",
            )

    def test_missing_stored_value_raises(self) -> None:
        with self.assertRaises(ValueError):
            assert_redirect_matches_state(None, "https://manus.example.com/login/callback")


if __name__ == "__main__":
    unittest.main()
