"""Release gate for doc/refactoring/GROK-BACKEND.md (R1-R10).

Each test class maps to one R item's contract. This file intentionally
overlaps with the dedicated test modules added alongside each R item — it
is the single file that must stay green for a release, even if those
modules are later renamed or reorganized.
"""

from __future__ import annotations

import re
import unittest
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.config import validate_trusted_proxy_ips
from core.database import get_db
from core.dev_tools import dev_tools_enabled, require_dev_tools
from core.models.users import User
from core.oidc_redirect import assert_redirect_matches_state, validate_oidc_redirect_uri
from core.production_guards import validate_non_development_secrets
from core.safe_hosts import validate_netmiko_preview_host
from core.safe_urls import UnsafeURLError, validate_git_remote_url
from models.settings import SettingCreate, SettingUpdate
from services.auth.rbac_service import RBACService
from services.settings.settings_service import SettingsService


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


# ---------------------------------------------------------------------------
# R1 — token-at-rest
# ---------------------------------------------------------------------------


def _setting(key: str, value: dict, setting_id: int = 1) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=setting_id, key=key, value=value, description=None, created_at=now, updated_at=now
    )


def _settings_service() -> SettingsService:
    service = SettingsService(MagicMock())
    service.repo = MagicMock()
    service._credentials = MagicMock()
    return service


class TestR1TokenAtRest(unittest.TestCase):
    def test_create_persists_credential_id_not_token(self) -> None:
        service = _settings_service()
        service.repo.get_by_key.return_value = None
        service._credentials.create_credential.return_value = {"id": 99}
        persisted: dict = {}

        def create(*, key: str, value: dict, description: str | None):
            persisted["value"] = dict(value)
            return _setting(key, persisted["value"])

        service.repo.create.side_effect = create

        with patch.object(
            SettingsService, "_validate_source_url", staticmethod(lambda t, v: v)
        ):
            response = service.create_setting(
                SettingCreate(
                    key="sources.nautobot.lab",
                    value={
                        "url": "https://nautobot.example.com",
                        "token": "nb-secret",
                    },
                ),
            )

        self.assertEqual(response.value["token"], "")
        self.assertNotIn("token", persisted["value"])
        self.assertEqual(persisted["value"]["credential_id"], 99)

    def test_get_source_config_decrypts_token(self) -> None:
        service = _settings_service()
        service.repo.get_by_key.return_value = _setting(
            "sources.nautobot.lab",
            {"url": "https://nautobot.example.com", "credential_id": 99},
        )
        service._credentials.get_decrypted_password.return_value = "nb-secret"

        config = service.get_source_config("nautobot", "lab")

        self.assertEqual(config["token"], "nb-secret")
        self.assertNotIn("credential_id", config)

    def test_get_setting_hides_credential_id_and_token(self) -> None:
        service = _settings_service()
        service.repo.get_by_key.return_value = _setting(
            "sources.nautobot.lab",
            {"url": "https://nautobot.example.com", "credential_id": 99},
        )

        result = service.get_setting("sources.nautobot.lab")

        self.assertEqual(result.value["token"], "")
        self.assertTrue(result.value["token_configured"])
        self.assertNotIn("credential_id", result.value)

    def test_update_blank_token_does_not_rotate_credential(self) -> None:
        service = _settings_service()
        existing = _setting(
            "sources.nautobot.lab",
            {"url": "https://nautobot.example.com", "credential_id": 99},
        )
        service.repo.get_by_key.return_value = existing
        service.repo.update.side_effect = lambda setting, fields: SimpleNamespace(
            **{**setting.__dict__, **fields}
        )

        with patch.object(
            SettingsService, "_validate_source_url", staticmethod(lambda t, v: v)
        ):
            service.update_setting(
                "sources.nautobot.lab",
                SettingUpdate(
                    value={
                        "url": "https://nautobot.example.com",
                        "token": "",
                    }
                ),
            )

        service._credentials.update_credential.assert_not_called()
        service._credentials.create_credential.assert_not_called()

    def test_delete_setting_deletes_linked_credential(self) -> None:
        service = _settings_service()
        existing = _setting(
            "sources.nautobot.lab",
            {"url": "https://nautobot.example.com", "credential_id": 99},
        )
        service.repo.get_by_key.return_value = existing

        service.delete_setting("sources.nautobot.lab")

        service._credentials.delete_credential.assert_called_once_with(99)

    def test_legacy_plaintext_row_still_resolves_in_get_source_config(self) -> None:
        service = _settings_service()
        service.repo.get_by_key.return_value = _setting(
            "sources.nautobot.lab",
            {"url": "https://nautobot.example.com", "token": "legacy-secret"},
        )

        config = service.get_source_config("nautobot", "lab")

        self.assertEqual(config["token"], "legacy-secret")
        service._credentials.get_decrypted_password.assert_not_called()


# ---------------------------------------------------------------------------
# R2 — production secret guards
# ---------------------------------------------------------------------------


class TestR2ProductionGuards(unittest.TestCase):
    def test_development_allows_defaults(self) -> None:
        validate_non_development_secrets(
            environment="development",
            secret_key="change-in-production-use-at-least-32-characters",
            initial_password="admin",
            credential_encryption_key="",
            database_password="postgres",
        )

    def test_production_rejects_default_secret_key(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_non_development_secrets(
                environment="production",
                secret_key="change-in-production-use-at-least-32-characters",
                initial_password="x" * 12,
                credential_encryption_key="y" * 32,
                database_password="strongpw",
            )

    def test_production_rejects_empty_credential_encryption_key(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_non_development_secrets(
                environment="production",
                secret_key="x" * 40,
                initial_password="x" * 12,
                credential_encryption_key="",
                database_password="strongpw",
            )

    def test_production_rejects_encryption_key_equal_to_secret_key(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_non_development_secrets(
                environment="production",
                secret_key="x" * 40,
                initial_password="x" * 12,
                credential_encryption_key="x" * 40,
                database_password="strongpw",
            )

    def test_production_rejects_weak_database_password(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_non_development_secrets(
                environment="production",
                secret_key="x" * 40,
                initial_password="x" * 12,
                credential_encryption_key="y" * 40,
                database_password="postgres",
            )

    def test_production_accepts_distinct_strong_secrets(self) -> None:
        validate_non_development_secrets(
            environment="production",
            secret_key="x" * 40,
            initial_password="x" * 12,
            credential_encryption_key="y" * 40,
            database_password="strongpw",
            redis_password="strong-redis",
        )

    def test_production_rejects_enable_dev_tools(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ENABLE_DEV_TOOLS"):
            validate_non_development_secrets(
                environment="production",
                secret_key="x" * 40,
                initial_password="x" * 12,
                credential_encryption_key="y" * 40,
                database_password="strongpw",
                redis_password="strong-redis",
                enable_dev_tools=True,
            )

    def test_production_rejects_empty_redis_password(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "MANUS_REDIS_PASSWORD"):
            validate_non_development_secrets(
                environment="production",
                secret_key="x" * 40,
                initial_password="x" * 12,
                credential_encryption_key="y" * 40,
                database_password="strongpw",
                redis_password="",
            )

    def test_production_rejects_allow_netmiko_arbitrary_hosts(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "ALLOW_NETMIKO_ARBITRARY_HOSTS"):
            validate_non_development_secrets(
                environment="production",
                secret_key="x" * 40,
                initial_password="x" * 12,
                credential_encryption_key="y" * 40,
                database_password="strongpw",
                redis_password="strong-redis",
                allow_netmiko_arbitrary_hosts=True,
            )

    def test_development_allows_dev_tools_and_empty_redis_password(self) -> None:
        validate_non_development_secrets(
            environment="development",
            secret_key="change-in-production-use-at-least-32-characters",
            initial_password="admin",
            credential_encryption_key="",
            database_password="postgres",
            enable_dev_tools=True,
            redis_password="",
            allow_netmiko_arbitrary_hosts=True,
        )


# ---------------------------------------------------------------------------
# R3 — git remote URL allow-list
# ---------------------------------------------------------------------------


class TestR3GitRemoteUrl(unittest.TestCase):
    @patch("core.safe_urls.socket.getaddrinfo")
    def test_accepts_https(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        self.assertEqual(
            validate_git_remote_url("https://git.example.com/org/repo.git"),
            "https://git.example.com/org/repo.git",
        )

    @patch("core.safe_urls.socket.getaddrinfo")
    def test_accepts_scp_like(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        self.assertEqual(
            validate_git_remote_url("git@git.example.com:org/repo.git"),
            "git@git.example.com:org/repo.git",
        )

    def test_rejects_file_scheme(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("file:///tmp/repo.git")

    def test_rejects_http_scheme_in_production(self) -> None:
        with patch("core.safe_urls.settings.environment", "production"):
            with self.assertRaises(UnsafeURLError):
                validate_git_remote_url("http://git.example.com/org/repo.git")

    @patch("core.safe_urls.socket.getaddrinfo")
    def test_allows_http_scheme_in_development(self, mock_getaddrinfo: MagicMock) -> None:
        mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("core.safe_urls.settings.environment", "development"):
            self.assertEqual(
                validate_git_remote_url("http://git.example.com/org/repo.git"),
                "http://git.example.com/org/repo.git",
            )

    def test_rejects_bare_path(self) -> None:
        with self.assertRaises(UnsafeURLError):
            validate_git_remote_url("/var/git/repo.git")

    @patch("services.git.connection.subprocess.run")
    def test_git_connection_service_rejects_file_scheme(self, mock_run: MagicMock) -> None:
        from models.git_repositories import GitAuthType, GitConnectionTestRequest
        from services.git.connection import GitConnectionService

        request = GitConnectionTestRequest(
            url="file:///tmp/x", auth_type=GitAuthType.TOKEN, token="secret"
        )
        result = GitConnectionService().test_connection(request)

        self.assertFalse(result.success)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# R4 — OIDC redirect_uri binding
# ---------------------------------------------------------------------------


class TestR4OidcRedirect(unittest.TestCase):
    def test_development_allows_localhost_login_callback(self) -> None:
        self.assertEqual(
            validate_oidc_redirect_uri(
                "http://localhost:3000/login/callback", allowlist=[], environment="development"
            ),
            "http://localhost:3000/login/callback",
        )

    def test_development_rejects_arbitrary_host(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "https://evil.example/callback", allowlist=[], environment="development"
            )

    def test_production_requires_allowlist(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "https://manus.example.com/login/callback",
                allowlist=[],
                environment="production",
            )

    def test_production_allowlist_match(self) -> None:
        self.assertEqual(
            validate_oidc_redirect_uri(
                "https://manus.example.com/login/callback",
                allowlist=["https://manus.example.com/login/callback"],
                environment="production",
            ),
            "https://manus.example.com/login/callback",
        )

    def test_production_allowlist_miss(self) -> None:
        with self.assertRaises(ValueError):
            validate_oidc_redirect_uri(
                "https://other.example.com/login/callback",
                allowlist=["https://manus.example.com/login/callback"],
                environment="production",
            )

    def test_callback_rejects_redirect_uri_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            assert_redirect_matches_state(
                "https://manus.example.com/login/callback", "https://evil.example/callback"
            )

    def test_callback_accepts_matching_redirect_uri(self) -> None:
        assert_redirect_matches_state(
            "https://manus.example.com/login/callback",
            "https://manus.example.com/login/callback",
        )


# ---------------------------------------------------------------------------
# R5 — dev-tools gate on break-glass routes
# ---------------------------------------------------------------------------


class TestR5DevToolsGate(unittest.TestCase):
    def test_dev_tools_disabled_when_env_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("ENABLE_DEV_TOOLS", None)
            self.assertFalse(dev_tools_enabled())

    def test_require_dev_tools_raises_404_when_disabled(self) -> None:
        with patch("core.dev_tools.dev_tools_enabled", return_value=False):
            with self.assertRaises(HTTPException) as ctx:
                require_dev_tools()
            self.assertEqual(ctx.exception.status_code, 404)

    def test_require_dev_tools_passes_when_enabled(self) -> None:
        with patch("core.dev_tools.dev_tools_enabled", return_value=True):
            require_dev_tools()  # must not raise

    def test_migrate_schema_returns_404_when_dev_tools_disabled(self) -> None:
        from routers.system import router as system_router

        app = FastAPI()
        app.include_router(system_router, prefix="/api")
        app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
        app.dependency_overrides[get_current_user] = _make_user
        app.dependency_overrides[get_db] = _override_db

        with (
            patch.object(RBACService, "has_permission", lambda self, *a, **k: True),
            patch("core.dev_tools.dev_tools_enabled", return_value=False),
            TestClient(app) as client,
        ):
            response = client.post("/api/system/schema/migrate")

        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# R6 — Netmiko preview host policy
# ---------------------------------------------------------------------------


class TestR6NetmikoHost(unittest.TestCase):
    def test_development_allows_rfc1918(self) -> None:
        self.assertEqual(
            validate_netmiko_preview_host(
                "10.1.2.3", environment="development", allow_arbitrary=False
            ),
            "10.1.2.3",
        )

    def test_rejects_metadata_ip_in_any_environment(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host(
                "169.254.169.254", environment="development", allow_arbitrary=True
            )

    def test_rejects_metadata_hostname(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host(
                "metadata.google.internal", environment="production", allow_arbitrary=True
            )

    def test_production_denies_by_default(self) -> None:
        with self.assertRaises(ValueError):
            validate_netmiko_preview_host(
                "10.1.2.3", environment="production", allow_arbitrary=False
            )

    def test_production_allows_when_arbitrary_enabled(self) -> None:
        self.assertEqual(
            validate_netmiko_preview_host(
                "10.1.2.3", environment="production", allow_arbitrary=True
            ),
            "10.1.2.3",
        )


# ---------------------------------------------------------------------------
# R7 — general_settings:read
# ---------------------------------------------------------------------------


class TestR7GeneralSettingsRead(unittest.TestCase):
    def _app(self) -> FastAPI:
        from models.general_settings import GeneralSettingsResponse
        from routers.general_settings import _service
        from routers.general_settings import router as general_settings_router

        app = FastAPI()
        app.include_router(general_settings_router, prefix="/api")
        app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
        app.dependency_overrides[get_current_user] = _make_user
        app.dependency_overrides[get_db] = _override_db
        mock_service = MagicMock()
        mock_service.get_settings.return_value = GeneralSettingsResponse(
            session_timeout_minutes=20,
            default_export_directory="",
            switch_to_runs_on_start=True,
            resolved_export_directory="/data/exports",
        )
        app.dependency_overrides[_service] = lambda: mock_service
        return app

    def test_denied_without_permission(self) -> None:
        with (
            patch.object(RBACService, "has_permission", lambda self, *a, **k: False),
            TestClient(self._app()) as client,
        ):
            response = client.get("/api/general/settings")
        self.assertEqual(response.status_code, 403)

    def test_allowed_with_permission(self) -> None:
        with (
            patch.object(RBACService, "has_permission", lambda self, *a, **k: True),
            TestClient(self._app()) as client,
        ):
            response = client.get("/api/general/settings")
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# R8 — dead code removed
# ---------------------------------------------------------------------------


class TestR8DeadSymbols(unittest.TestCase):
    def test_get_cached_commits_removed(self) -> None:
        import routers.git.operations as ops

        self.assertFalse(hasattr(ops, "get_cached_commits"))

    def test_plugins_has_no_token_preview_models(self) -> None:
        import models.plugins as plugins

        self.assertFalse(hasattr(plugins, "DeviceSelectionPreviewRequest"))
        self.assertFalse(hasattr(plugins, "FieldValuesRequest"))

    def test_device_update_service_has_no_create_if_missing(self) -> None:
        import inspect

        from services.nautobot.devices.update import DeviceUpdateService

        signature = inspect.signature(DeviceUpdateService.update_device)
        self.assertNotIn("create_if_missing", signature.parameters)


# ---------------------------------------------------------------------------
# R9 — workflow_steps import boundary
# ---------------------------------------------------------------------------


class TestR9StepBoundary(unittest.TestCase):
    def test_no_workflow_steps_import_outside_registry(self) -> None:
        services_dir = Path(__file__).resolve().parents[2] / "services"
        allowed = {"execution/step_registry.py"}
        import_pattern = re.compile(r"^\s*(import workflow_steps|from workflow_steps)", re.M)

        offenders = []
        for path in services_dir.rglob("*.py"):
            rel = path.relative_to(services_dir).as_posix()
            if rel in allowed:
                continue
            if import_pattern.search(path.read_text()):
                offenders.append(rel)

        self.assertEqual(offenders, [])

    def test_device_template_moved_to_workflow_context(self) -> None:
        from services.workflow_context import device_template

        self.assertTrue(hasattr(device_template, "render_device_template"))


# ---------------------------------------------------------------------------
# R10 — /health/ready
# ---------------------------------------------------------------------------


class TestR10Ready(unittest.TestCase):
    def test_ping_database_success(self) -> None:
        from core.database import ping_database

        mock_session = MagicMock()
        mock_session.__enter__.return_value = mock_session
        mock_session.__exit__.return_value = False

        with patch("core.database.SessionLocal", return_value=mock_session):
            ping_database()

        mock_session.execute.assert_called_once()

    def test_ready_response_200_when_both_ok(self) -> None:
        from services.health.ready import build_ready_response

        status_code, body = build_ready_response(
            database_ok=True, database_error=None, redis_ok=True, redis_error=None
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(body.status, "ok")

    def test_ready_response_503_when_database_down(self) -> None:
        from services.health.ready import build_ready_response

        status_code, body = build_ready_response(
            database_ok=False, database_error="unavailable", redis_ok=True, redis_error=None
        )
        self.assertEqual(status_code, 503)
        self.assertEqual(body.status, "unavailable")

    def test_ready_response_503_when_redis_down(self) -> None:
        from services.health.ready import build_ready_response

        status_code, body = build_ready_response(
            database_ok=True, database_error=None, redis_ok=False, redis_error="unconfigured"
        )
        self.assertEqual(status_code, 503)
        self.assertEqual(body.status, "unavailable")


# ---------------------------------------------------------------------------
# M8 — TRUSTED_PROXY_IPS hardening
# ---------------------------------------------------------------------------


class TestM8TrustedProxyIps(unittest.TestCase):
    def test_accepts_valid_ips(self) -> None:
        result = validate_trusted_proxy_ips({"10.0.0.1", "192.168.1.1"})
        self.assertEqual(result, {"10.0.0.1", "192.168.1.1"})

    def test_empty_set_is_allowed(self) -> None:
        self.assertEqual(validate_trusted_proxy_ips(set()), set())

    def test_rejects_invalid_ip(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_trusted_proxy_ips({"not-an-ip"})

    def test_rejects_unspecified_ipv4(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_trusted_proxy_ips({"0.0.0.0"})

    def test_rejects_unspecified_ipv6(self) -> None:
        with self.assertRaises(RuntimeError):
            validate_trusted_proxy_ips({"::"})


if __name__ == "__main__":
    unittest.main()
