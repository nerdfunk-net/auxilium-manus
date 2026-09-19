"""Tests for BatfishSourceConfigService: settings-only, no credential to manage."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.source_config_service import (
    BatfishSourceConfigService,
    BatfishSourceConflictError,
    BatfishSourceNotFoundError,
)


def _setting(key: str, value: dict) -> SimpleNamespace:
    return SimpleNamespace(key=key, value=value, description=None)


class BatfishSourceConfigServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        settings_patcher = patch("services.batfish.source_config_service.SettingsRepository")
        self.mock_settings_cls = settings_patcher.start()
        self.addCleanup(settings_patcher.stop)
        self.mock_settings = self.mock_settings_cls.return_value

        # No real DNS in unit tests; the policy tests below override side_effect.
        validate_patcher = patch(
            "services.batfish.source_config_service.validate_outbound_http_url",
            side_effect=lambda url, *, resolve_dns=True: url,
        )
        self.mock_validate = validate_patcher.start()
        self.addCleanup(validate_patcher.stop)

        self.service = BatfishSourceConfigService(db=MagicMock())

    def test_create_source_stores_host_and_port(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_settings.create.return_value = _setting(
            "sources.batfish.lab",
            {
                "host": "batfish",
                "port": 9996,
                "source_id": "lab",
                "source_type": "batfish",
            },
        )

        result = self.service.create_source(source_id="lab", host="batfish")

        create_kwargs = self.mock_settings.create.call_args.kwargs
        self.assertEqual(create_kwargs["key"], "sources.batfish.lab")
        self.assertEqual(create_kwargs["value"]["host"], "batfish")
        self.assertEqual(create_kwargs["value"]["port"], 9996)
        self.assertEqual(result["host"], "batfish")
        self.assertEqual(result["port"], 9996)
        self.assertEqual(result["source_id"], "lab")

    def test_create_source_custom_port(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_settings.create.return_value = _setting(
            "sources.batfish.lab", {"host": "10.0.0.5", "port": 9999, "source_id": "lab"}
        )

        self.service.create_source(source_id="lab", host="10.0.0.5", port=9999)

        create_kwargs = self.mock_settings.create.call_args.kwargs
        self.assertEqual(create_kwargs["value"]["port"], 9999)

    def test_create_source_rejects_blank_host(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with self.assertRaises(BatfishValidationError):
            self.service.create_source(source_id="lab", host="   ")
        self.mock_settings.create.assert_not_called()

    def test_create_source_conflict_raises(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting("sources.batfish.lab", {})
        with self.assertRaises(BatfishSourceConflictError):
            self.service.create_source(source_id="lab", host="batfish")
        self.mock_settings.create.assert_not_called()

    def test_update_source_without_host_keeps_existing_port(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9996}
        )
        self.mock_settings.update.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9997}
        )

        result = self.service.update_source("lab", port=9997)

        updated_value = self.mock_settings.update.call_args.args[1]["value"]
        self.assertEqual(updated_value["host"], "batfish")
        self.assertEqual(updated_value["port"], 9997)
        self.assertEqual(result["port"], 9997)

    def test_update_source_missing_raises_not_found(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        with self.assertRaises(BatfishSourceNotFoundError):
            self.service.update_source("missing", host="batfish")

    def test_delete_source_removes_setting(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish"}
        )
        self.service.delete_source("lab")
        self.mock_settings.delete.assert_called_once()

    def test_resolve_connection_returns_host_and_port(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9996}
        )

        connection = self.service.resolve_connection("lab")

        self.assertEqual(connection.host, "batfish")
        self.assertEqual(connection.port, 9996)

    def test_resolve_connection_defaults_port_when_missing(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish"}
        )

        connection = self.service.resolve_connection("lab")

        self.assertEqual(connection.port, 9996)

    def test_resolve_inline_connection_no_settings_lookup(self) -> None:
        connection = self.service.resolve_inline_connection(host="127.0.0.1", port=9996)
        self.mock_settings.get_by_key.assert_not_called()
        self.assertEqual(connection.host, "127.0.0.1")
        self.assertEqual(connection.port, 9996)

    def test_resolve_inline_connection_rejects_blank_host(self) -> None:
        with self.assertRaises(BatfishValidationError):
            self.service.resolve_inline_connection(host="", port=9996)

    def test_list_sources_exposes_host_and_port(self) -> None:
        self.mock_settings.list_all.return_value = [
            _setting("sources.batfish.lab", {"host": "batfish", "port": 9996, "source_id": "lab"}),
        ]
        result = self.service.list_sources()
        self.assertEqual(result[0]["host"], "batfish")
        self.assertEqual(result[0]["port"], 9996)

    # ---- B1: outbound policy ----------------------------------------------
    def test_create_source_applies_outbound_policy_with_dns(self) -> None:
        self.mock_settings.get_by_key.return_value = None
        self.mock_settings.create.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9996, "source_id": "lab"}
        )
        self.service.create_source(source_id="lab", host="batfish", port=9996)
        self.mock_validate.assert_called_once_with("http://batfish:9996", resolve_dns=True)

    def test_create_source_rejects_disallowed_target(self) -> None:
        from core.safe_urls import UnsafeURLError

        self.mock_settings.get_by_key.return_value = None
        self.mock_validate.side_effect = UnsafeURLError("URL resolves to link-local address")
        with self.assertRaisesRegex(BatfishValidationError, "not allowed"):
            self.service.create_source(source_id="lab", host="169.254.169.254", port=80)
        self.mock_settings.create.assert_not_called()

    def test_update_port_only_revalidates_pair(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9996, "source_id": "lab"}
        )
        self.mock_settings.update.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9999, "source_id": "lab"}
        )
        self.service.update_source("lab", port=9999)
        self.mock_validate.assert_called_once_with("http://batfish:9999", resolve_dns=True)

    def test_resolve_connection_rechecks_without_dns(self) -> None:
        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab", {"host": "batfish", "port": 9996, "source_id": "lab"}
        )
        connection = self.service.resolve_connection("lab")
        self.assertEqual((connection.host, connection.port), ("batfish", 9996))
        self.mock_validate.assert_called_once_with("http://batfish:9996", resolve_dns=False)

    def test_resolve_connection_refuses_legacy_disallowed_row(self) -> None:
        from core.safe_urls import UnsafeURLError

        self.mock_settings.get_by_key.return_value = _setting(
            "sources.batfish.lab",
            {"host": "metadata.google.internal", "port": 80, "source_id": "lab"},
        )
        self.mock_validate.side_effect = UnsafeURLError("URL host is not allowed")
        with self.assertRaises(BatfishValidationError):
            self.service.resolve_connection("lab")

    def test_inline_connection_applies_policy_with_dns(self) -> None:
        self.service.resolve_inline_connection(host="10.0.0.5", port=9996)
        self.mock_validate.assert_called_once_with("http://10.0.0.5:9996", resolve_dns=True)


if __name__ == "__main__":
    unittest.main()
