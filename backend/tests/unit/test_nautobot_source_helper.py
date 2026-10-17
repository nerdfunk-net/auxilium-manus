"""Tests for workflow_steps/common/nautobot_source.py.

The 5 Nautobot-facing step executors (get-nautobot-devices, get-nautobot-attributes,
get-ise-devices, add-to-nautobot, update-nautobot-device) all resolve their source
through ``resolve_nautobot_credentials``. The token lives in the ``credentials``
table behind ``credential_id`` — never inline in the setting value — so the resolver
must go through ``SettingsService.get_source_config_for_step`` (which resolves it)
rather than reading ``setting.value["token"]`` directly.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.credentials.exceptions import CredentialNotFoundError
from services.settings.exceptions import SourceConfigError
from workflow_steps.common import nautobot_source as mod
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials


class ResolveNautobotCredentialsTests(unittest.TestCase):
    def _patch_settings(self, **kwargs):
        """Patch SettingsService so get_source_config_for_step behaves per kwargs."""
        service = MagicMock()
        service.get_source_config_for_step.configure_mock(**kwargs)
        return patch.object(mod, "SettingsService", return_value=service)

    def test_blank_source_id_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_nautobot_credentials(MagicMock(), "  ", step_id="get-nautobot-devices")
        self.assertIn("nautobot_source_id is not configured", str(ctx.exception))

    def test_credential_id_backed_token_is_resolved(self) -> None:
        # SettingsService.get_source_config_for_step already swapped credential_id -> token.
        config = {"url": "https://nb.lab/", "token": "resolved-token", "verify_ssl": False}
        with self._patch_settings(return_value=config):
            creds = resolve_nautobot_credentials(
                MagicMock(), "lab", step_id="get-nautobot-devices"
            )
        self.assertEqual(creds.url, "https://nb.lab")
        self.assertEqual(creds.token, "resolved-token")
        self.assertFalse(creds.verify_ssl)

    def test_verify_ssl_defaults_true_when_absent(self) -> None:
        config = {"url": "https://nb.lab", "token": "t"}
        with self._patch_settings(return_value=config):
            creds = resolve_nautobot_credentials(
                MagicMock(), "lab", step_id="get-nautobot-attributes"
            )
        self.assertEqual(creds.token, "t")
        self.assertTrue(creds.verify_ssl)

    def test_unknown_source_raises_value_error_with_step_prefix(self) -> None:
        with self._patch_settings(
            side_effect=SourceConfigError("Nautobot source 'lab' not found in settings")
        ):
            with self.assertRaises(ValueError) as ctx:
                resolve_nautobot_credentials(MagicMock(), "lab", step_id="get-ise-devices")
        message = str(ctx.exception)
        self.assertIn("get-ise-devices:", message)
        self.assertIn("not found in settings", message)

    def test_missing_url_or_token_raises(self) -> None:
        for config in ({"url": "", "token": "t"}, {"url": "https://nb", "token": ""}):
            with self.subTest(config=config):
                with self._patch_settings(return_value=config):
                    with self.assertRaises(ValueError) as ctx:
                        resolve_nautobot_credentials(
                            MagicMock(), "lab", step_id="add-to-nautobot"
                        )
                self.assertIn("is missing url or token", str(ctx.exception))

    def test_dangling_credential_id_raises_value_error(self) -> None:
        with self._patch_settings(side_effect=CredentialNotFoundError(42)):
            with self.assertRaises(ValueError) as ctx:
                resolve_nautobot_credentials(
                    MagicMock(), "lab", step_id="update-nautobot-device"
                )
        self.assertIn("update-nautobot-device:", str(ctx.exception))
        self.assertIn("credential is missing", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
