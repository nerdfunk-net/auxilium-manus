"""routers/auth.py::login — two independent failure budgets (T1 / D2)."""

from __future__ import annotations

import unittest
from ipaddress import ip_network
from unittest.mock import MagicMock, patch

import redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.database import get_db
from dependencies import get_login_ip_rate_limiter, get_login_user_rate_limiter
from routers.auth import router as auth_router
from services.auth.auth_service import AuthenticationError
from services.auth.login_rate_limiter import LoginRateLimiter

# The TestClient's direct peer must be a trusted proxy for X-Forwarded-For to
# be honoured by core.client_ip.resolve_client_host.
_PROXY_PEER = ("127.0.0.1", 12345)


def _make_limiter(attempts: int) -> LoginRateLimiter:
    limiter = LoginRateLimiter(
        redis_url="redis://localhost:6379/0", attempts=attempts, window_seconds=60
    )
    limiter._redis = MagicMock()
    limiter._redis.pipeline.side_effect = redis.ConnectionError("down")
    return limiter


class AuthLoginRateLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ip_limiter = _make_limiter(attempts=3)
        self.user_limiter = _make_limiter(attempts=3)

        self.app = FastAPI()
        self.app.include_router(auth_router, prefix="/api")
        self.app.dependency_overrides[get_db] = lambda: MagicMock()
        self.app.dependency_overrides[get_login_ip_rate_limiter] = lambda: self.ip_limiter
        self.app.dependency_overrides[get_login_user_rate_limiter] = lambda: self.user_limiter

        self._settings_patch = patch(
            "core.client_ip.settings.trusted_proxy_networks",
            frozenset({ip_network("127.0.0.1/32")}),
        )
        self._settings_patch.start()
        self.addCleanup(self._settings_patch.stop)

    def _client(self) -> TestClient:
        return TestClient(self.app, client=_PROXY_PEER)

    def _login(self, client: TestClient, username: str, *, ip: str = "1.2.3.4") -> object:
        return client.post(
            "/api/auth/login",
            json={"username": username, "password": "wrong"},
            headers={"X-Forwarded-For": ip},
        )

    def test_username_budget_blocks_after_n_failures_regardless_of_ip(self) -> None:
        with (
            patch(
                "routers.auth.AuthService.authenticate_user",
                side_effect=AuthenticationError("bad creds"),
            ) as mock_auth,
            self._client() as client,
        ):
            responses = [
                self._login(client, "alice", ip=f"10.0.0.{i}") for i in range(1, 4)
            ]
            for response in responses:
                self.assertEqual(response.status_code, 401)

            fourth = self._login(client, "alice", ip="10.0.0.9")
            self.assertEqual(fourth.status_code, 429)
            self.assertEqual(mock_auth.call_count, 3)

    def test_ip_budget_blocks_across_usernames(self) -> None:
        with (
            patch(
                "routers.auth.AuthService.authenticate_user",
                side_effect=AuthenticationError("bad creds"),
            ),
            self._client() as client,
        ):
            for username in ("alice", "bob", "carol"):
                response = self._login(client, username, ip="9.9.9.9")
                self.assertEqual(response.status_code, 401)

            fourth = self._login(client, "dave", ip="9.9.9.9")
            self.assertEqual(fourth.status_code, 429)

    def test_success_does_not_consume_budget_and_clears_user_bucket(self) -> None:
        user = MagicMock()
        with (
            patch(
                "routers.auth.AuthService.authenticate_user",
                side_effect=[
                    AuthenticationError("bad creds"),
                    AuthenticationError("bad creds"),
                    user,
                ],
            ),
            patch(
                "routers.auth.AuthService.create_access_token",
                return_value=("tok", 60),
            ),
            self._client() as client,
        ):
            self.assertEqual(self._login(client, "alice", ip="5.5.5.5").status_code, 401)
            self.assertEqual(self._login(client, "alice", ip="5.5.5.6").status_code, 401)
            success = self._login(client, "alice", ip="5.5.5.7")
            self.assertEqual(success.status_code, 200)

        # The username bucket was cleared by the success, so two more failures
        # are allowed before the (attempts=3) budget trips again.
        self.assertEqual(len(self.user_limiter._fallback_attempts.get("user:alice", [])), 0)
        # The IP bucket is never cleared by a success from a different IP each
        # time, but the first two IPs still hold their recorded failures.
        self.assertEqual(len(self.ip_limiter._fallback_attempts.get("ip:5.5.5.5", [])), 1)
        self.assertEqual(len(self.ip_limiter._fallback_attempts.get("ip:5.5.5.6", [])), 1)

    def test_success_from_another_account_does_not_clear_ip_bucket(self) -> None:
        user = MagicMock()
        with (
            patch(
                "routers.auth.AuthService.authenticate_user",
                side_effect=[
                    AuthenticationError("bad creds"),
                    AuthenticationError("bad creds"),
                    user,
                ],
            ),
            patch(
                "routers.auth.AuthService.create_access_token",
                return_value=("tok", 60),
            ),
            self._client() as client,
        ):
            self.assertEqual(self._login(client, "alice", ip="7.7.7.7").status_code, 401)
            self.assertEqual(self._login(client, "bob", ip="7.7.7.7").status_code, 401)
            success = self._login(client, "carol", ip="7.7.7.7")
            self.assertEqual(success.status_code, 200)

        # carol's success must not have cleared the shared IP bucket's earlier
        # two failures — a third failure from that IP trips the attempts=3 budget.
        self.assertEqual(len(self.ip_limiter._fallback_attempts.get("ip:7.7.7.7", [])), 2)


if __name__ == "__main__":
    unittest.main()
