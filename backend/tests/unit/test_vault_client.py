"""OpenBaoService KV v2 request shaping, error mapping, and TTL cache."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import httpx

from services.vault.client import OpenBaoService
from services.vault.config import VaultConfig
from services.vault.exceptions import (
    VaultAuthError,
    VaultPermissionError,
    VaultSecretNotFoundError,
    VaultUnavailableError,
)


def _resp(status_code: int, body: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = body if body is not None else {}
    return response


def _service() -> OpenBaoService:
    cfg = VaultConfig(
        addr="https://vault.test:8200",
        mount="manus",
        auth_method="token",
        token="root-token",
        cache_ttl_seconds=45,
    )
    svc = OpenBaoService(cfg)
    svc._client = MagicMock()
    return svc


class OpenBaoServiceTests(unittest.TestCase):
    def test_read_kv_unwraps_and_caches(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(
            200, {"data": {"data": {"password": "s3cr3t"}}}
        )

        first = svc.read_kv("credentials/lab-switch-1")
        second = svc.read_kv("credentials/lab-switch-1")

        self.assertEqual(first, {"password": "s3cr3t"})
        self.assertEqual(second, {"password": "s3cr3t"})
        # cache hit -> only one HTTP call
        self.assertEqual(svc._client.request.call_count, 1)
        method, path = svc._client.request.call_args[0][:2]
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/v1/manus/data/credentials/lab-switch-1")
        headers = svc._client.request.call_args[1]["headers"]
        self.assertEqual(headers["X-Vault-Token"], "root-token")

    def test_write_kv_sends_data_envelope_and_refreshes_cache(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(204)

        svc.write_kv("credentials/lab-switch-1", {"token": "abc"})

        method, path = svc._client.request.call_args[0][:2]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/v1/manus/data/credentials/lab-switch-1")
        self.assertEqual(
            svc._client.request.call_args[1]["json"], {"data": {"token": "abc"}}
        )
        # writer sees its own write without another HTTP call
        self.assertEqual(svc.read_kv("credentials/lab-switch-1"), {"token": "abc"})
        self.assertEqual(svc._client.request.call_count, 1)

    def test_delete_kv_invalidates_cache(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(200, {"data": {"data": {"token": "x"}}})
        svc.read_kv("credentials/c")
        svc._client.request.return_value = _resp(204)
        svc.delete_kv("credentials/c")
        self.assertEqual(svc._client.request.call_args[0][0], "DELETE")
        # next read must go back to the network
        svc._client.request.return_value = _resp(200, {"data": {"data": {"token": "y"}}})
        self.assertEqual(svc.read_kv("credentials/c"), {"token": "y"})

    def test_404_maps_to_secret_not_found(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(404)
        with self.assertRaises(VaultSecretNotFoundError):
            svc.read_kv("credentials/missing")

    def test_403_invalidates_token_and_raises_permission(self) -> None:
        svc = _service()
        svc._tokens.ensure_token(svc._client)
        svc._client.request.return_value = _resp(403)
        with self.assertRaises(VaultPermissionError):
            svc.read_kv("credentials/denied")
        with self.assertRaises(VaultAuthError):
            svc._tokens.current()  # token was dropped

    def test_connect_error_maps_to_unavailable_and_is_not_cached(self) -> None:
        svc = _service()
        svc._client.request.side_effect = httpx.ConnectError("no route to host")
        with self.assertRaises(VaultUnavailableError):
            svc.read_kv("credentials/c")

        # recovery: a later successful read still hits the network
        svc._client.request.side_effect = None
        svc._client.request.return_value = _resp(200, {"data": {"data": {"token": "ok"}}})
        self.assertEqual(svc.read_kv("credentials/c"), {"token": "ok"})

    def test_5xx_maps_to_unavailable(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(502)
        with self.assertRaises(VaultUnavailableError):
            svc.read_kv("credentials/c")

    def test_request_before_startup_raises_unavailable(self) -> None:
        svc = OpenBaoService(
            VaultConfig(addr="https://vault.test", auth_method="token", token="t")
        )
        with self.assertRaises(VaultUnavailableError):
            svc.read_kv("credentials/c")


if __name__ == "__main__":
    unittest.main()
