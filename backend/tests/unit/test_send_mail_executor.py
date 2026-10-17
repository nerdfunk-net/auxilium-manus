"""Tests for send-mail executor (mocked aiosmtplib + credential vault, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiosmtplib

from models.mail import MailSettings
from models.workflow_context import DeviceContext, WorkflowContext
from services.mail.errors import MailCredentialError
from workflow_steps.send_mail.executor import execute

_BASE_CONFIG = {
    "to": "ops@example.com",
    "subject": "Workflow finished",
    "body": "Devices: {devices}",
}

_SEND = "services.mail.smtp_sender.aiosmtplib.send"
_CONN = "workflow_steps.send_mail.executor.MailService"
_GLOBAL = MailSettings(
    smtp_server="smtp.admin.example",
    smtp_port=587,
    security="starttls",
    verify_tls=True,
    from_address="manus@admin.example",
)
_SESSION = "workflow_steps.send_mail.executor.object_session"


def _device(device_id: str, *, name: str | None = None, attribute_bags: dict | None = None):
    resolved_name = name or device_id
    return DeviceContext(
        id=device_id,
        name=resolved_name,
        hostname=resolved_name,
        attribute_bags=attribute_bags or {},
    )


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    run.triggered_by_id = 7
    return run


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


async def _execute(config: dict, context: WorkflowContext | None = None):
    return await execute(
        config=config,
        context=context or _context({"d1": _device("d1", name="router1")}),
        run=_run(),
        artifact_service=MagicMock(),
        node_id="send-mail-1",
        device_sessions=MagicMock(),
    )


class SendMailExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def _run_ok(
        self,
        config: dict,
        context: WorkflowContext | None = None,
        settings: MailSettings = _GLOBAL,
        credentials: tuple[str | None, str | None] = ("smtp-user", "s3cret-pw"),
    ):
        send = AsyncMock(return_value=({}, "OK"))
        with (
            patch(_SEND, send),
            patch(_SESSION, return_value=MagicMock()),
            patch(_CONN) as service,
        ):
            service.return_value.connection.return_value = (settings, *credentials)
            outcomes = await _execute(config, context)
        return outcomes, send

    async def test_sends_through_the_global_settings_with_the_global_credential(self) -> None:
        outcomes, send = await self._run_ok(_BASE_CONFIG)

        self.assertEqual(outcomes[0].name, "success")
        send.assert_awaited_once()
        message = send.call_args.args[0]
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["hostname"], "smtp.admin.example")
        self.assertEqual(kwargs["port"], 587)
        self.assertTrue(kwargs["start_tls"])
        self.assertEqual(kwargs["username"], "smtp-user")
        self.assertEqual(kwargs["password"], "s3cret-pw")
        self.assertEqual(message["From"], "manus@admin.example")
        self.assertEqual(message["To"], "ops@example.com")
        self.assertEqual(message["Subject"], "Workflow finished")
        self.assertIn("router1", message.get_content())

    async def test_step_config_cannot_choose_the_smtp_server(self) -> None:
        """S3-02 / S4-09: server, port, credential and sender in the step are ignored."""
        hostile = {
            **_BASE_CONFIG,
            "smtp_server": "attacker.example",
            "smtp_port": 25,
            "security": "none",
            "credential_reference": "admin-global-cred",
            "from_address": "ceo@victim.example",
        }
        _, send = await self._run_ok(hostile)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["hostname"], "smtp.admin.example")
        self.assertEqual(kwargs["port"], 587)
        self.assertEqual(send.call_args.args[0]["From"], "manus@admin.example")

    async def test_global_ssl_and_tls_verification_settings_apply(self) -> None:
        settings = _GLOBAL.model_copy(
            update={"security": "ssl", "smtp_port": 465, "verify_tls": False}
        )
        _, send = await self._run_ok(_BASE_CONFIG, settings=settings)
        kwargs = send.call_args.kwargs
        self.assertTrue(kwargs["use_tls"])
        self.assertFalse(kwargs["validate_certs"])

    async def test_no_global_credential_sends_without_auth(self) -> None:
        _, send = await self._run_ok(_BASE_CONFIG, credentials=(None, None))
        self.assertIsNone(send.call_args.kwargs["username"])
        self.assertIsNone(send.call_args.kwargs["password"])

    async def test_disallowed_recipient_domain_fails(self) -> None:
        settings = _GLOBAL.model_copy(update={"allowed_recipient_domains": ["corp.example"]})
        send = AsyncMock()
        with (
            patch(_SEND, send),
            patch(_SESSION, return_value=MagicMock()),
            patch(_CONN) as service,
            self.assertRaisesRegex(ValueError, "not allowed"),
        ):
            service.return_value.connection.return_value = (settings, None, None)
            await _execute(_BASE_CONFIG)
        send.assert_not_awaited()

    async def test_step_without_mail_settings_fails_clearly(self) -> None:
        with (
            patch(_SESSION, return_value=MagicMock()),
            patch(_CONN) as service,
            self.assertRaisesRegex(ValueError, "not configured"),
        ):
            service.return_value.connection.return_value = (MailSettings(), None, None)
            await _execute(_BASE_CONFIG)

    async def test_unusable_global_credential_fails_clearly(self) -> None:
        with (
            patch(_SESSION, return_value=MagicMock()),
            patch(_CONN) as service,
            self.assertRaises(ValueError),
        ):
            service.return_value.connection.side_effect = MailCredentialError("nope")
            await _execute(_BASE_CONFIG)

    async def test_multiple_recipients_split_on_comma_and_semicolon(self) -> None:
        _, send = await self._run_ok(
            {**_BASE_CONFIG, "to": "a@example.com; b@example.com, c@example.com"}
        )
        message = send.call_args.args[0]
        self.assertEqual(
            sorted(a.strip() for a in message["To"].split(",")),
            ["a@example.com", "b@example.com", "c@example.com"],
        )

    async def test_subject_and_body_placeholders_resolve_per_device(self) -> None:
        context = _context({"d1": _device("d1", name="router1")})
        _, send = await self._run_ok(
            {**_BASE_CONFIG, "subject": "On {device.name}", "body": "Host {device.name}"}, context
        )
        message = send.call_args.args[0]
        self.assertEqual(message["Subject"], "On router1")
        self.assertIn("Host router1", message.get_content())

    async def test_zero_devices_with_device_placeholder_skips_send(self) -> None:
        outcomes, send = await self._run_ok(
            {**_BASE_CONFIG, "subject": "On {device.name}"}, _context({})
        )
        self.assertEqual(outcomes[0].name, "success")
        send.assert_not_awaited()

    async def test_missing_required_fields_raise_value_error(self) -> None:
        for key in ("to", "subject", "body"):
            config = {k: v for k, v in _BASE_CONFIG.items() if k != key}
            with self.subTest(key=key), self.assertRaises(ValueError):
                await self._run_ok(config)

    async def test_invalid_email_address_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await self._run_ok({**_BASE_CONFIG, "to": "not-an-address"})

    async def test_header_injection_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            await self._run_ok({**_BASE_CONFIG, "subject": "hi\nBcc: evil@example.com"})

    async def test_smtp_error_returns_failure_without_leaking_password(self) -> None:
        send = AsyncMock(side_effect=aiosmtplib.SMTPAuthenticationError(535, "bad creds s3cret-pw"))
        with (
            patch(_SEND, send),
            patch(_SESSION, return_value=MagicMock()),
            patch(_CONN) as service,
        ):
            service.return_value.connection.return_value = (_GLOBAL, "smtp-user", "s3cret-pw")
            outcomes = await _execute(_BASE_CONFIG)
        self.assertEqual(outcomes[0].name, "failure")
        self.assertNotIn("s3cret-pw", outcomes[0].summary)

    async def test_connection_error_returns_failure(self) -> None:
        send = AsyncMock(side_effect=OSError("connection refused"))
        with (
            patch(_SEND, send),
            patch(_SESSION, return_value=MagicMock()),
            patch(_CONN) as service,
        ):
            service.return_value.connection.return_value = (_GLOBAL, None, None)
            outcomes = await _execute(_BASE_CONFIG)
        self.assertEqual(outcomes[0].name, "failure")


if __name__ == "__main__":
    unittest.main()
