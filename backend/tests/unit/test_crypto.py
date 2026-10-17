"""Unit tests for core.crypto and the KDF_ITERATIONS setting (S12)."""

from __future__ import annotations

import unittest
from unittest import mock

from core import config, crypto, crypto_policy
from core.crypto import EncryptionService, _build_key


class BuildKeyCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        _build_key.cache_clear()
        self.addCleanup(_build_key.cache_clear)

    def test_same_inputs_return_the_cached_object(self) -> None:
        first = _build_key("a-high-entropy-secret", 100_000)
        second = _build_key("a-high-entropy-secret", 100_000)
        self.assertIs(first, second)
        self.assertGreaterEqual(_build_key.cache_info().hits, 1)

    def test_iteration_count_is_part_of_the_cache_key(self) -> None:
        self.assertNotEqual(
            _build_key("a-high-entropy-secret", 100_000),
            _build_key("a-high-entropy-secret", 200_000),
        )

    def test_pbkdf2_stretches_once_across_many_service_constructions(self) -> None:
        # Regression for FABLE_BACKEND_20260902.md §4.2: PBKDF2 used to run on every
        # EncryptionService() (i.e. every credentials request), stalling the loop.
        with (
            mock.patch.object(crypto, "_iterations", return_value=100_000),
            mock.patch("core.crypto.PBKDF2HMAC", wraps=crypto.PBKDF2HMAC) as spy,
        ):
            for _ in range(5):
                EncryptionService("a-high-entropy-secret")
        self.assertEqual(spy.call_count, 1)


class IterationsFromSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        _build_key.cache_clear()
        self.addCleanup(_build_key.cache_clear)

    def test_encryption_service_derives_key_with_settings_iterations(self) -> None:
        with (
            mock.patch.object(crypto, "_iterations", return_value=150_000),
            mock.patch.object(crypto, "_build_key", wraps=crypto._build_key) as spy,
        ):
            EncryptionService("a-high-entropy-secret")
        spy.assert_called_once_with("a-high-entropy-secret", 150_000)

    def test_iterations_reads_from_settings(self) -> None:
        with mock.patch.object(config.settings, "kdf_iterations", 123_456):
            self.assertEqual(crypto._iterations(), 123_456)


class EncryptRoundTripTests(unittest.TestCase):
    def test_encrypt_decrypt_round_trip(self) -> None:
        svc = EncryptionService("test-secret-key-for-crypto-tests")
        token = svc.encrypt("hunter2")
        self.assertEqual(svc.decrypt(token), "hunter2")

    def test_decrypt_rejects_tampered_token(self) -> None:
        svc = EncryptionService("test-secret-key-for-crypto-tests")
        with self.assertRaises(ValueError):
            svc.decrypt(b"not-a-valid-fernet-token")


class KdfIterationsFloorTests(unittest.TestCase):
    """The suite lowers the floor (conftest); these tests pin the production value explicitly."""

    def setUp(self) -> None:
        patcher = mock.patch.object(crypto_policy, "KDF_ITERATIONS_FLOOR", 600_000)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_production_floor_is_600k(self) -> None:
        self.assertEqual(crypto_policy.KDF_ITERATIONS_FLOOR, 600_000)

    def test_settings_rejects_iterations_below_floor_and_above_ceiling(self) -> None:
        for value in ("99999", "599999", "5000001"):
            with mock.patch.dict("os.environ", {"KDF_ITERATIONS": value}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "KDF_ITERATIONS"):
                    config.Settings()

    def test_settings_accepts_iterations_at_floor(self) -> None:
        with mock.patch.dict("os.environ", {"KDF_ITERATIONS": "600000"}, clear=False):
            self.assertEqual(config.Settings().kdf_iterations, 600_000)


class VersionedFormatTests(unittest.TestCase):
    SECRET = "test-secret-key-for-crypto-tests-0123456789"

    def setUp(self) -> None:
        _build_key.cache_clear()
        self.addCleanup(_build_key.cache_clear)

    def test_round_trip_and_prefix(self) -> None:
        svc = EncryptionService(self.SECRET)
        token = svc.encrypt("hunter2")
        self.assertTrue(token.startswith(b"AMS2.1000."))
        self.assertEqual(svc.decrypt(token), "hunter2")

    def test_token_carries_iteration_count(self) -> None:
        """A value made with one count still decrypts after the setting changes."""
        svc = EncryptionService(self.SECRET)
        token = svc.encrypt("hunter2")
        with mock.patch.object(crypto, "_iterations", return_value=2_000):
            later = EncryptionService(self.SECRET)
            self.assertEqual(later.decrypt(token), "hunter2")
            self.assertTrue(later.encrypt("x").startswith(b"AMS2.2000."))

    def test_legacy_fernet_token_is_rejected(self) -> None:
        from cryptography.fernet import Fernet

        legacy = Fernet(Fernet.generate_key()).encrypt(b"old")
        with self.assertRaisesRegex(ValueError, "older version"):
            EncryptionService(self.SECRET).decrypt(legacy)

    def test_iterations_below_floor_and_above_ceiling_are_rejected_without_deriving(self) -> None:
        svc = EncryptionService(self.SECRET)
        body = svc.encrypt("x").decode().split(".", 2)[2]
        with mock.patch.object(crypto, "_build_key") as derive:
            for iterations in ("10", "999", "999999999"):
                with self.assertRaises(ValueError):
                    svc.decrypt(f"AMS2.{iterations}.{body}".encode())
            derive.assert_not_called()

    def test_no_fernet_outside_crypto_module(self) -> None:
        import re
        from pathlib import Path

        backend = Path(__file__).resolve().parents[2]
        offenders = []
        for path in backend.rglob("*.py"):
            rel = path.relative_to(backend).as_posix()
            if rel.startswith(("tests/", ".venv/", "scripts/")) or rel == "core/crypto.py":
                continue
            if re.search(r"\bFernet\(", path.read_text(encoding="utf-8")):
                offenders.append(rel)
        self.assertEqual(offenders, [])


class RefreshWindowCapTests(unittest.TestCase):
    def test_refresh_window_above_session_cap_is_refused(self) -> None:
        env = {"SESSION_MAX_AGE_HOURS": "12", "REFRESH_TOKEN_MAX_AGE_HOURS": "13"}
        with mock.patch.dict("os.environ", env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "REFRESH_TOKEN_MAX_AGE_HOURS"):
                config.Settings()

    def test_refresh_window_defaults_to_session_cap(self) -> None:
        env = {"SESSION_MAX_AGE_HOURS": "8"}
        with mock.patch.dict("os.environ", env, clear=False):
            os_env = __import__("os").environ
            os_env.pop("REFRESH_TOKEN_MAX_AGE_HOURS", None)
            self.assertEqual(config.Settings().refresh_token_max_age_hours, 8)


if __name__ == "__main__":
    unittest.main()
