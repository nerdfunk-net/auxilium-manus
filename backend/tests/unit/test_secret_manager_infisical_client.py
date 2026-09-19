"""InfisicalSecretManagerClient wire shaping via httpx.MockTransport:
login, 401 retry-once, create-vs-update, 404 -> None, and the strict
ensure_started (SM1)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import httpx

from services.secret_manager.config import SecretManagerConnectionConfig
from services.secret_manager.exceptions import (
    SecretManagerAuthError,
    SecretManagerConfigError,
    SecretManagerPermissionError,
)


def _cfg(**overrides) -> SecretManagerConnectionConfig:
    base = dict(
        id=2,
        name="inf",
        backend="infisical",
        verify_ssl=True,
        backend_config={
            "site_url": "https://infisical.example",
            "project_id": "proj",
            "environment": "prod",
        },
        auth_id="client-id",
        auth_secret="client-secret",
    )
    return SecretManagerConnectionConfig(**{**base, **overrides})


class _Fake:
    """Scripted Infisical: records requests, answers per (method, path)."""

    def __init__(self, *, login_status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.login_status = login_status
        self.secrets: dict[str, str] = {}
        self.deny_next = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/v1/auth/universal-auth/login":
            if self.login_status != 200:
                return httpx.Response(self.login_status, json={})
            return httpx.Response(200, json={"accessToken": "tok", "expiresIn": 7200})
        if self.deny_next:
            self.deny_next -= 1
            return httpx.Response(401, json={})
        key = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            if key not in self.secrets:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"secret": {"secretValue": self.secrets[key]}})
        body = json.loads(request.content or b"{}")
        self.secrets[key] = body.get("secretValue", "")
        version = 1 if request.method == "POST" else 2
        return httpx.Response(200, json={"secret": {"version": version}})


_RealHttpxClient = httpx.Client


class InfisicalSecretManagerClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        env = patch("services.secret_manager.transport_policy.settings.environment", "development")
        env.start()
        self.addCleanup(env.stop)
        self.fake = _Fake()
        # Capture the real httpx.Client before patching -- patching
        # "...httpx.Client" replaces the attribute on the shared httpx module,
        # so the side_effect must not call back through the (now-patched)
        # `httpx.Client` name or it recurses into itself.
        client_patcher = patch(
            "services.secret_manager.infisical_client.httpx.Client",
            side_effect=lambda **kw: _RealHttpxClient(
                base_url=kw["base_url"], transport=httpx.MockTransport(self.fake.handler)
            ),
        )
        client_patcher.start()
        self.addCleanup(client_patcher.stop)
        from services.secret_manager.infisical_client import InfisicalSecretManagerClient

        self.cls = InfisicalSecretManagerClient

    def test_missing_project_is_config_error(self) -> None:
        with self.assertRaises(SecretManagerConfigError):
            self.cls(_cfg(backend_config={"site_url": "https://x", "environment": "prod"}))

    def test_verify_ssl_false_outside_development_is_config_error(self) -> None:
        with patch("services.secret_manager.transport_policy.settings.environment", "production"):
            with self.assertRaisesRegex(SecretManagerConfigError, "verify_ssl=false"):
                self.cls(_cfg(verify_ssl=False))

    # ---- ensure_started (SM1) -----------------------------------------------
    async def test_ensure_started_logs_in(self) -> None:
        await self.cls(_cfg()).ensure_started()
        self.assertEqual([r.url.path for r in self.fake.requests],
                         ["/api/v1/auth/universal-auth/login"])

    async def test_ensure_started_raises_on_bad_credentials(self) -> None:
        self.fake.login_status = 401
        with self.assertRaises(SecretManagerAuthError):
            await self.cls(_cfg()).ensure_started()

    async def test_ensure_started_raises_without_credentials(self) -> None:
        with self.assertRaises(SecretManagerConfigError):
            await self.cls(_cfg(auth_secret="")).ensure_started()

    # ---- wire shaping -------------------------------------------------------
    def test_get_field_404_returns_none(self) -> None:
        self.assertIsNone(self.cls(_cfg()).get_field("network/r1/tacacs", "key"))

    def test_set_field_creates_then_updates(self) -> None:
        client = self.cls(_cfg())
        self.assertEqual(client.set_field("p", "key", "v1"), 1)
        self.assertEqual(client.set_field("p", "key", "v2"), 2)
        methods = [r.method for r in self.fake.requests if r.url.path.endswith("/secrets/key")]
        self.assertEqual(methods, ["GET", "POST", "GET", "PATCH"])
        self.assertEqual(self.fake.secrets["key"], "v2")

    def test_401_triggers_relogin_and_one_retry(self) -> None:
        client = self.cls(_cfg())
        self.fake.secrets["key"] = "v"
        self.fake.deny_next = 1
        self.assertEqual(client.get_field("p", "key"), "v")
        logins = [r for r in self.fake.requests if r.url.path.endswith("/login")]
        self.assertEqual(len(logins), 2)

    def test_persistent_403_is_permission_error(self) -> None:
        client = self.cls(_cfg())
        self.fake.deny_next = 2
        with self.assertRaises(SecretManagerPermissionError):
            client.get_field("p", "key")

    def test_secret_path_is_query_param_and_field_is_path(self) -> None:
        self.cls(_cfg()).get_field("network/r1/tacacs", "key")
        get = [r for r in self.fake.requests if r.method == "GET"][0]
        self.assertTrue(get.url.path.endswith("/api/v4/secrets/key"))
        self.assertEqual(get.url.params["secretPath"], "network/r1/tacacs")


if __name__ == "__main__":
    unittest.main()
