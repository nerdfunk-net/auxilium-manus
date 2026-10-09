"""OpenBaoService KV v2 request shaping, error mapping, and TTL cache."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpx

from services.vault.client import OpenBaoService
from services.vault.config import VaultConfig
from services.vault.exceptions import (
    VaultConflictError,
    VaultError,
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
        method, path = svc._client.request.call_args[0][:2]
        self.assertEqual(method, "DELETE")
        # V3: delete goes through the metadata endpoint (destroys every version),
        # not a plain data-path delete (which would only soft-delete the latest).
        self.assertEqual(path, "/v1/manus/metadata/credentials/c")
        # next read must go back to the network
        svc._client.request.return_value = _resp(200, {"data": {"data": {"token": "y"}}})
        self.assertEqual(svc.read_kv("credentials/c"), {"token": "y"})

    def test_write_kv_returns_version(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(200, {"data": {"version": 3}})
        self.assertEqual(svc.write_kv("credentials/c", {"token": "abc"}), 3)

    def test_write_kv_returns_none_without_version(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(204)
        self.assertIsNone(svc.write_kv("credentials/c", {"token": "abc"}))

    def test_destroy_kv_versions_posts_versions(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(204)
        svc.destroy_kv_versions("credentials/c", [2])
        method, path = svc._client.request.call_args[0][:2]
        self.assertEqual(method, "POST")
        self.assertEqual(path, "/v1/manus/destroy/credentials/c")
        self.assertEqual(svc._client.request.call_args[1]["json"], {"versions": [2]})

    def test_destroy_kv_versions_noop_for_empty_list(self) -> None:
        svc = _service()
        svc.destroy_kv_versions("credentials/c", [])
        svc._client.request.assert_not_called()

    def test_404_maps_to_secret_not_found(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(404)
        with self.assertRaises(VaultSecretNotFoundError):
            svc.read_kv("credentials/missing")

    def test_second_403_raises_permission_and_keeps_fresh_token(self) -> None:
        svc = _service()
        svc._tokens.ensure_token(svc._client)
        svc._client.request.return_value = _resp(403)
        with self.assertRaises(VaultPermissionError):
            svc.read_kv("credentials/denied")
        # Re-logged-in once (V4) and denied again -> the token is kept, not dropped.
        self.assertEqual(svc._client.request.call_count, 2)
        self.assertEqual(svc._tokens.current(), "root-token")

    def test_403_then_200_is_retried_transparently(self) -> None:
        svc = _service()
        svc._tokens.ensure_token(svc._client)
        svc._client.request.side_effect = [
            _resp(403),
            _resp(200, {"data": {"data": {"token": "ok"}}}),
        ]
        self.assertEqual(svc.read_kv("credentials/c"), {"token": "ok"})
        self.assertEqual(svc._client.request.call_count, 2)

    def test_403_with_valid_token_does_not_relogin(self) -> None:
        # V7: lookup-self says the token is fine -> genuine policy denial, no re-login.
        svc = _service()
        svc._tokens.ensure_token(svc._client)
        svc._client.request.return_value = _resp(403)
        svc._client.get.return_value = _resp(200)
        with patch.object(svc._tokens, "invalidate") as invalidate:
            with self.assertRaises(VaultPermissionError):
                svc.read_kv("credentials/denied")
        invalidate.assert_not_called()
        self.assertEqual(svc._client.request.call_count, 1)
        self.assertEqual(svc._client.get.call_args[0][0], "/v1/auth/token/lookup-self")

    def test_403_with_invalid_token_relogs_in_once(self) -> None:
        svc = _service()
        svc._tokens.ensure_token(svc._client)
        svc._client.get.return_value = _resp(403)
        svc._client.request.side_effect = [
            _resp(403),
            _resp(200, {"data": {"data": {"token": "ok"}}}),
        ]
        with patch.object(svc._tokens, "invalidate") as invalidate:
            self.assertEqual(svc.read_kv("credentials/c"), {"token": "ok"})
        invalidate.assert_called_once()

    def test_write_kv_sends_cas(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(204)
        svc.write_kv("credentials/c", {"a": "1"}, cas=3)
        self.assertEqual(
            svc._client.request.call_args[1]["json"],
            {"data": {"a": "1"}, "options": {"cas": 3}},
        )

    def test_cas_mismatch_maps_to_conflict(self) -> None:
        svc = _service()
        bad = _resp(400)
        bad.text = "check-and-set parameter did not match the current version"
        svc._client.request.return_value = bad
        with self.assertRaises(VaultConflictError):
            svc.write_kv("credentials/c", {"a": "1"}, cas=1)

    def _read_resp(self, data: dict, version: int) -> MagicMock:
        return _resp(200, {"data": {"data": data, "metadata": {"version": version}}})

    def test_merge_kv_merges_with_current_version_as_cas(self) -> None:
        svc = _service()
        svc._client.request.side_effect = [
            self._read_resp({"a": "1"}, 4),
            _resp(200, {"data": {"version": 5}}),
        ]
        merged, version = svc.merge_kv("credentials/c", {"b": "2"})
        self.assertEqual(merged, {"a": "1", "b": "2"})
        self.assertEqual(version, 5)
        self.assertEqual(svc._client.request.call_args[1]["json"]["options"], {"cas": 4})

    def test_merge_kv_creates_with_cas_zero(self) -> None:
        svc = _service()
        svc._client.request.side_effect = [
            _resp(404),
            _resp(404),
            _resp(200, {"data": {"version": 1}}),
        ]
        merged, _ = svc.merge_kv("credentials/c", {"b": "2"})
        self.assertEqual(merged, {"b": "2"})
        self.assertEqual(svc._client.request.call_args[1]["json"]["options"], {"cas": 0})

    def test_merge_kv_retries_once_on_cas_conflict(self) -> None:
        svc = _service()
        conflict = _resp(400)
        conflict.text = "check-and-set parameter did not match"
        svc._client.request.side_effect = [
            self._read_resp({"a": "1"}, 1),
            conflict,
            self._read_resp({"a": "1", "x": "9"}, 2),
            _resp(200, {"data": {"version": 3}}),
        ]
        merged, version = svc.merge_kv("credentials/c", {"b": "2"})
        self.assertEqual(merged, {"a": "1", "x": "9", "b": "2"})
        self.assertEqual(version, 3)

    def test_merge_kv_second_conflict_raises(self) -> None:
        svc = _service()
        conflict = _resp(400)
        conflict.text = "check-and-set parameter did not match"
        svc._client.request.side_effect = [
            self._read_resp({}, 1),
            conflict,
            self._read_resp({}, 2),
            conflict,
        ]
        with self.assertRaises(VaultConflictError):
            svc.merge_kv("credentials/c", {"b": "2"})

    def test_merge_kv_rewrites_soft_deleted_secret_with_current_version(self) -> None:
        svc = _service()
        svc._client.request.side_effect = [
            _resp(404),  # data read: soft-deleted
            _resp(200, {"data": {"current_version": 4, "versions": {}}}),  # metadata
            _resp(200, {"data": {"version": 5}}),
        ]
        merged, version = svc.merge_kv("credentials/c", {"b": "2"})
        self.assertEqual((merged, version), ({"b": "2"}, 5))
        self.assertEqual(svc._client.request.call_args[1]["json"]["options"], {"cas": 4})

    def test_invalidate_drops_cache(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(200, {"data": {"data": {"t": "x"}}})
        svc.read_kv("credentials/c")
        svc.invalidate("credentials/c")
        svc.read_kv("credentials/c")
        self.assertEqual(svc._client.request.call_count, 2)

    def test_unauthed_403_is_not_retried(self) -> None:
        svc = _service()
        svc._client.request.return_value = _resp(403)
        with self.assertRaises(VaultPermissionError):
            svc.health()
        self.assertEqual(svc._client.request.call_count, 1)

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


class OpenBaoServiceHealthyTests(unittest.IsolatedAsyncioTestCase):
    """SM1: ``healthy`` reflects whether the last login/renew actually worked."""

    async def test_healthy_false_after_failed_startup(self) -> None:
        cfg = VaultConfig(addr="https://vault.test:8200", auth_method="token", token="t")
        svc = OpenBaoService(cfg)
        with patch.object(svc._tokens, "ensure_token", side_effect=VaultError("bad token")):
            await svc.startup()
        self.assertFalse(svc.healthy)
        await svc.shutdown()

    async def test_healthy_true_after_successful_startup(self) -> None:
        cfg = VaultConfig(addr="https://vault.test:8200", auth_method="token", token="t")
        svc = OpenBaoService(cfg)
        with patch.object(svc._tokens, "ensure_token"):
            await svc.startup()
        self.assertTrue(svc.healthy)
        await svc.shutdown()


if __name__ == "__main__":
    unittest.main()
