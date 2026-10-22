"""Tests for AgentSourceConfigService: transport + identity + a global shared-secret credential."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.safe_urls import UnsafeURLError
from core.secret_policy import MIN_AGENT_SECRET_LENGTH
from services.agents.exceptions import AgentValidationError
from services.agents.source_config_service import (
    AgentSourceConfigService,
    AgentSourceConflictError,
    AgentSourceNotFoundError,
)
from services.credentials.source_credentials import SourceCredentialError

SECRET = "k" * MIN_AGENT_SECRET_LENGTH
_MODULE = "services.agents.source_config_service"


def _setting(key: str, value: dict) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value, description=None)


class AgentSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_settings_cls = self._patch(
            "services.settings.source_config_base.SettingsRepository"
        )
        self.mock_validate = self._patch(f"{_MODULE}.validate_outbound_http_url")
        self.mock_assert = self._patch(f"{_MODULE}.assert_global_credential")
        self.mock_resolve = self._patch(f"{_MODULE}.resolve_global_secret")
        self.mock_creds_cls = self._patch(f"{_MODULE}.CredentialsService")
        self.mock_settings = self.mock_settings_cls.return_value
        self.mock_validate.side_effect = lambda url, *, resolve_dns=True: url
        self.mock_resolve.return_value = ("agent", SECRET)
        self.mock_creds_cls.return_value.get_credential_by_id.return_value = {"name": "agent-key"}
        self.service = AgentSourceConfigService(db=MagicMock())

    def _patch(self, target: str) -> MagicMock:
        patcher = patch(target)
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def _create(self, **overrides):
        self.mock_settings.get_by_key.return_value = None
        self.mock_settings.create.side_effect = lambda key, value, description: _setting(
            key, value
        )
        kwargs = {
            "source_id": "geo",
            "transport": "http",
            "agent_id": "agent-geo",
            "url": "http://geo-agent:8080",
            "credential_id": 7,
        }
        kwargs.update(overrides)
        return self.service.create_source(**kwargs)

    def test_create_http_source_stores_defaults(self) -> None:
        result = self._create()
        value = self.mock_settings.create.call_args.kwargs["value"]
        self.assertEqual(self.mock_settings.create.call_args.kwargs["key"], "sources.agent.geo")
        self.assertEqual(value["transport"], "http")
        self.assertEqual(value["url"], "http://geo-agent:8080")
        self.assertEqual(value["agent_id"], "agent-geo")
        self.assertEqual(value["credential_id"], 7)
        self.assertEqual(value["max_concurrency"], 4)
        self.assertEqual(value["max_request_bytes"], 1_048_576)
        self.assertEqual(value["max_timeout_seconds"], 60)
        self.assertEqual(result["credential_name"], "agent-key")
        self.assertNotIn(SECRET, str(result))

    def test_create_redis_source_ignores_url(self) -> None:
        self._create(transport="redis", url=None)
        value = self.mock_settings.create.call_args.kwargs["value"]
        self.assertEqual(value["transport"], "redis")
        self.assertIsNone(value["url"])
        self.mock_validate.assert_not_called()

    def test_http_requires_url(self) -> None:
        with self.assertRaises(AgentValidationError):
            self._create(url=None)

    def test_url_policy_violation_is_a_validation_error(self) -> None:
        self.mock_validate.side_effect = UnsafeURLError("link-local")
        with self.assertRaises(AgentValidationError):
            self._create()

    def test_unknown_transport_and_bad_agent_id(self) -> None:
        with self.assertRaises(AgentValidationError):
            self._create(transport="carrier-pigeon")
        for bad in ("", "has space", "x" * 65, "a:b", "UPPER*"):
            with self.subTest(agent_id=bad), self.assertRaises(AgentValidationError):
                self._create(agent_id=bad)

    def test_numeric_limits_are_bounded(self) -> None:
        for field, bad in (
            ("max_concurrency", 0),
            ("max_concurrency", 65),
            ("max_request_bytes", 1023),
            ("max_request_bytes", 9 * 1024 * 1024),
            ("max_timeout_seconds", 0),
            ("max_timeout_seconds", 601),
        ):
            with self.subTest(field=field, value=bad), self.assertRaises(AgentValidationError):
                self._create(**{field: bad})

    def test_credential_must_be_global_shared_secret(self) -> None:
        self.mock_assert.side_effect = SourceCredentialError("not global")
        with self.assertRaises(AgentValidationError):
            self._create()

    def test_short_secret_is_rejected_at_save_time(self) -> None:
        self.mock_resolve.return_value = ("agent", "short-secret")
        with self.assertRaises(AgentValidationError) as ctx:
            self._create()
        self.assertNotIn("short-secret", str(ctx.exception))

    def test_duplicate_source_conflicts(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting("sources.agent.geo", {})
        with self.assertRaises(AgentSourceConflictError):
            self.service.create_source(
                source_id="geo", transport="redis", agent_id="a", credential_id=7
            )

    def test_update_revalidates_resulting_transport(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.agent.geo",
            {
                "source_id": "geo",
                "transport": "redis",
                "url": None,
                "agent_id": "a",
                "credential_id": 7,
                "max_concurrency": 4,
                "max_request_bytes": 1_048_576,
                "max_timeout_seconds": 60,
            },
        )
        self.mock_settings.update.side_effect = lambda setting, changes: SimpleNamespace(
            value=changes["value"]
        )
        # switching to http without a url is invalid
        with self.assertRaises(AgentValidationError):
            self.service.update_source("geo", transport="http")
        result = self.service.update_source("geo", transport="http", url="http://x:1")
        self.assertEqual(result["transport"], "http")
        self.assertEqual(result["url"], "http://x:1")

    def test_missing_source(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with self.assertRaises(AgentSourceNotFoundError):
            self.service.get_source("nope")

    def test_resolve_returns_connection_with_secret(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.agent.geo",
            {
                "source_id": "geo",
                "transport": "http",
                "url": "http://geo-agent:8080",
                "agent_id": "agent-geo",
                "credential_id": 7,
                "max_concurrency": 2,
                "max_request_bytes": 2048,
                "max_timeout_seconds": 10,
            },
        )
        conn = self.service.resolve_connection("geo")
        self.assertEqual(conn.agent_id, "agent-geo")
        self.assertEqual(conn.transport, "http")
        self.assertEqual(conn.secret, SECRET)
        self.assertEqual(conn.max_concurrency, 2)
        self.assertNotIn(SECRET, repr(conn))
        # no DNS on the worker hot path
        self.assertFalse(self.mock_validate.call_args.kwargs["resolve_dns"])


if __name__ == "__main__":
    unittest.main()
