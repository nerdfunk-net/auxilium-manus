"""Unit tests for core.crypto and the KDF_ITERATIONS setting (S12)."""

from __future__ import annotations

import unittest
from unittest import mock

from core import config, crypto
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
    def test_settings_rejects_iterations_below_floor(self) -> None:
        with mock.patch.dict("os.environ", {"KDF_ITERATIONS": "99999"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "KDF_ITERATIONS"):
                config.Settings()

    def test_settings_accepts_iterations_at_floor(self) -> None:
        with mock.patch.dict("os.environ", {"KDF_ITERATIONS": "100000"}, clear=False):
            self.assertEqual(config.Settings().kdf_iterations, 100_000)


if __name__ == "__main__":
    unittest.main()
