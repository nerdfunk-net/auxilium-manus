"""Tests for send-mail executor (mocked aiosmtplib + credential vault, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiosmtplib

from models.workflow_context import DeviceContext, WorkflowContext
from workflow_steps.common.credential_resolver import (
    CredentialReferenceInvalidError,
    CredentialReferenceNotFoundError,
)
from workflow_steps.send_mail.executor import execute

_BASE_CONFIG = {
    "smtp_server": "smtp.example.com",
    "smtp_port": 587,
    "security": "starttls",
    "credential_reference": "mail-relay",
    "from_address": "manus@example.com",
    "to": "ops@example.com",
    "subject": "Workflow finished",
    "body": "Devices: {devices}",
}

_SEND = "workflow_steps.send_mail.executor.aiosmtplib.send"
_CREDS = "workflow_steps.send_mail.executor.resolve_generic_only_credential"
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
    async def _run_ok(self, config: dict, context: WorkflowContext | None = None):
        send = AsyncMock(return_value=({}, "OK"))
        with (
            patch(_SEND, send),
            patch(_SESSION, return_value=MagicMock()),
            patch(_CREDS, return_value=("smtp-user", "s3cret-pw")),
        ):
            outcomes = await _execute(config, context)
        return outcomes, send

    async def test_starttls_sends_with_credentials(self) -> None:
        outcomes, send = await self._run_ok(_BASE_CONFIG)

        self.assertEqual(outcomes[0].name, "success")
        send.assert_awaited_once()
        message = send.call_args.args[0]
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["hostname"], "smtp.example.com")
        self.assertEqual(kwargs["port"], 587)
        self.assertTrue(kwargs["start_tls"])
        self.assertFalse(kwargs["use_tls"])
        self.assertEqual(kwargs["username"], "smtp-user")
        self.assertEqual(kwargs["password"], "s3cret-pw")
        self.assertEqual(message["From"], "manus@example.com")
        self.assertEqual(message["To"], "ops@example.com")
        self.assertEqual(message["Subject"], "Workflow finished")
        self.assertIn("router1", message.get_content())

    async def test_ssl_uses_implicit_tls(self) -> None:
        _, send = await self._run_ok({**_BASE_CONFIG, "security": "ssl", "smtp_port": 465})
        kwargs = send.call_args.kwargs
        self.assertTrue(kwargs["use_tls"])
        self.assertFalse(kwargs["start_tls"])
        self.assertEqual(kwargs["port"], 465)

    async def test_none_disables_tls(self) -> None:
        _, send = await self._run_ok(
            {**_BASE_CONFIG, "security": "none", "smtp_port": 25, "credential_reference": ""}
        )
        kwargs = send.call_args.kwargs
        self.assertFalse(kwargs["use_tls"])
        self.assertFalse(kwargs["start_tls"])

    async def test_certificate_validation_is_on_by_default(self) -> None:
        # Config saved before verify_tls existed has no such key: must stay secure.
        _, send = await self._run_ok(_BASE_CONFIG)
        self.assertTrue(send.call_args.kwargs["validate_certs"])

    async def test_verify_tls_false_disables_certificate_validation(self) -> None:
        # e.g. Proton Mail Bridge serves a locally generated self-signed certificate.
        _, send = await self._run_ok({**_BASE_CONFIG, "verify_tls": False})
        self.assertFalse(send.call_args.kwargs["validate_certs"])
        self.assertTrue(send.call_args.kwargs["start_tls"])

    async def test_verify_tls_true_keeps_certificate_validation(self) -> None:
        _, send = await self._run_ok({**_BASE_CONFIG, "verify_tls": True})
        self.assertTrue(send.call_args.kwargs["validate_certs"])

    async def test_no_credential_sends_without_auth(self) -> None:
        send = AsyncMock(return_value=({}, "OK"))
        creds = MagicMock()
        with patch(_SEND, send), patch(_SESSION, return_value=MagicMock()), patch(_CREDS, creds):
            await _execute({**_BASE_CONFIG, "credential_reference": ""})
        creds.assert_not_called()
        self.assertIsNone(send.call_args.kwargs["username"])
        self.assertIsNone(send.call_args.kwargs["password"])

    async def test_multiple_recipients_split_on_comma_and_semicolon(self) -> None:
        _, send = await self._run_ok(
            {**_BASE_CONFIG, "to": "a@example.com; b@example.com, c@example.com"}
        )
        self.assertEqual(
            send.call_args.kwargs["recipients"],
            ["a@example.com", "b@example.com", "c@example.com"],
        )

    async def test_subject_and_body_placeholders_resolve_per_device(self) -> None:
        device = _device(
            "d1", name="router1", attribute_bags={"nautobot": {"location": {"name": "core"}}}
        )
        config = {
            **_BASE_CONFIG,
            "subject": "Config changed on {device.name}",
            "body": "{device.name} is in {nautobot.location.name} ({device_count} device)",
        }
        _, send = await self._run_ok(config, _context({"d1": device}))
        message = send.call_args.args[0]
        self.assertEqual(message["Subject"], "Config changed on router1")
        self.assertIn("router1 is in core (1 device)", message.get_content())

    async def test_to_address_supports_placeholder(self) -> None:
        device = _device("d1", attribute_bags={"custom": {"owner_email": "net@example.com"}})
        _, send = await self._run_ok(
            {**_BASE_CONFIG, "to": "{custom.owner_email}"}, _context({"d1": device})
        )
        self.assertEqual(send.call_args.kwargs["recipients"], ["net@example.com"])

    async def test_multi_device_body_has_one_line_per_device_subject_uses_first(self) -> None:
        context = _context({"d1": _device("d1", name="r1"), "d2": _device("d2", name="r2")})
        config = {**_BASE_CONFIG, "subject": "Check {device.name}", "body": "Down: {device.name}"}
        _, send = await self._run_ok(config, context)
        message = send.call_args.args[0]
        self.assertEqual(message["Subject"], "Check r1")
        body = message.get_content()
        self.assertIn("Down: r1", body)
        self.assertIn("Down: r2", body)

    async def test_zero_devices_with_device_placeholder_skips_send(self) -> None:
        send = AsyncMock()
        with patch(_SEND, send), patch(_SESSION, return_value=MagicMock()), patch(_CREDS):
            outcomes = await _execute(
                {**_BASE_CONFIG, "body": "{device.name} failed"}, _context({})
            )
        send.assert_not_awaited()
        self.assertEqual(outcomes[0].name, "success")
        self.assertIn("skipped", outcomes[0].summary)

    async def test_zero_devices_with_run_level_placeholders_still_sends(self) -> None:
        _, send = await self._run_ok(
            {**_BASE_CONFIG, "body": "{device_count} devices"}, _context({})
        )
        send.assert_awaited_once()

    async def test_missing_required_fields_raise_value_error(self) -> None:
        for key in ("smtp_server", "from_address", "to", "subject", "body"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                await _execute({**_BASE_CONFIG, key: ""})

    async def test_invalid_port_raises_value_error(self) -> None:
        for port in (0, 70000, "abc", None):
            with self.subTest(port=port), self.assertRaises(ValueError):
                await _execute({**_BASE_CONFIG, "smtp_port": port})

    async def test_invalid_security_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await _execute({**_BASE_CONFIG, "security": "tls13"})

    async def test_invalid_email_address_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await _execute({**_BASE_CONFIG, "to": "not-an-address"})
        with self.assertRaises(ValueError):
            await _execute({**_BASE_CONFIG, "from_address": "also bad"})

    async def test_header_injection_is_rejected(self) -> None:
        device = _device("d1", name="r1\r\nBcc: attacker@example.com")
        with self.assertRaises(ValueError):
            await self._run_ok(
                {**_BASE_CONFIG, "subject": "Down: {device.name}"}, _context({"d1": device})
            )

    async def test_credential_with_plain_security_is_refused(self) -> None:
        send = AsyncMock(return_value=({}, "OK"))
        creds = MagicMock(return_value=("smtp-user", "s3cret-pw"))
        with (
            patch(_SEND, send),
            patch(_SESSION, return_value=MagicMock()),
            patch(_CREDS, creds),
            self.assertRaises(ValueError),
        ):
            await _execute({**_BASE_CONFIG, "security": "none", "smtp_port": 25})
        creds.assert_not_called()
        send.assert_not_awaited()

    async def test_ssh_credential_is_rejected(self) -> None:
        with (
            patch(_SESSION, return_value=MagicMock()),
            patch(_CREDS, side_effect=CredentialReferenceInvalidError("wrong type")),
            self.assertRaises(ValueError),
        ):
            await _execute(_BASE_CONFIG)

    async def test_unknown_credential_raises_value_error(self) -> None:
        with (
            patch(_SESSION, return_value=MagicMock()),
            patch(_CREDS, side_effect=CredentialReferenceNotFoundError("nope")),
            self.assertRaises(ValueError),
        ):
            await _execute(_BASE_CONFIG)

    async def test_smtp_error_returns_failure_without_leaking_password(self) -> None:
        send = AsyncMock(side_effect=aiosmtplib.SMTPAuthenticationError(535, "bad creds s3cret-pw"))
        with (
            patch(_SEND, send),
            patch(_SESSION, return_value=MagicMock()),
            patch(_CREDS, return_value=("smtp-user", "s3cret-pw")),
        ):
            outcomes = await _execute(_BASE_CONFIG)
        self.assertEqual(outcomes[0].name, "failure")
        self.assertNotIn("s3cret-pw", outcomes[0].summary)

    async def test_connection_error_returns_failure(self) -> None:
        send = AsyncMock(side_effect=OSError("connection refused"))
        with (
            patch(_SEND, send),
            patch(_SESSION, return_value=MagicMock()),
            patch(_CREDS, return_value=("u", "p")),
        ):
            outcomes = await _execute(_BASE_CONFIG)
        self.assertEqual(outcomes[0].name, "failure")


if __name__ == "__main__":
    unittest.main()
