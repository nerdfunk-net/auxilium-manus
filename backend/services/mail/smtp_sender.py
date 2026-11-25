"""Send an email through the global SMTP settings (aiosmtplib).

Shared by everything that mails from the application. Failures carry the exception class and the
SMTP status code only: server text may echo credentials.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from email.message import EmailMessage

import aiosmtplib

from models.failure import FailureInfo
from models.mail import MailSettings
from services.mail.errors import MailNotConfiguredError, MailSendError

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 30.0
PDF_MIME = ("application", "pdf")


def build_message(
    *,
    sender: str,
    recipients: Sequence[str],
    subject: str,
    text: str,
    html: str | None = None,
    attachments: Sequence[tuple[str, bytes]] = (),
) -> EmailMessage:
    """A multipart message: plain text, optional HTML alternative, optional PDF attachments.

    The caller passes bare, validated addresses and a single-line subject (``clean_address``)."""
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(text)
    if html is not None:
        message.add_alternative(html, subtype="html")
    for filename, data in attachments:
        message.add_attachment(data, maintype=PDF_MIME[0], subtype=PDF_MIME[1], filename=filename)
    return message


_AUTH_CODES = frozenset({530, 534, 535})


def _classify(exc: Exception, code: object) -> FailureInfo:
    name = type(exc).__name__
    if code in _AUTH_CODES:
        return FailureInfo(
            phase="auth", kind="auth_failed", exception_type=name, hint="check_credentials"
        )
    if isinstance(exc, TimeoutError) or "Timeout" in name:
        return FailureInfo(
            phase="connect",
            kind="timeout",
            retryable=True,
            exception_type=name,
            hint="check_reachability",
        )
    if isinstance(exc, OSError) or "Connect" in name:
        return FailureInfo(
            phase="connect", kind="unknown", exception_type=name, hint="check_reachability"
        )
    return FailureInfo(phase="api", kind="unknown", exception_type=name)


def _failure(settings: MailSettings, exc: Exception) -> MailSendError:
    code = getattr(exc, "code", None)
    suffix = f" (SMTP {code})" if code is not None else ""
    return MailSendError(
        f"could not send mail via {settings.smtp_server}:{settings.smtp_port}: "
        f"{type(exc).__name__}{suffix}",
        failure=_classify(exc, code),
    )


def _require_configured(settings: MailSettings) -> None:
    if not settings.smtp_server or not settings.from_address:
        raise MailNotConfiguredError("Mail is not configured: set the server and sender address")


async def send_message(
    settings: MailSettings, message: EmailMessage, *, username: str | None, password: str | None
) -> None:
    _require_configured(settings)
    recipients = [part.strip() for part in str(message["To"]).split(",") if part.strip()]
    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_server,
            port=settings.smtp_port,
            sender=settings.from_address,
            recipients=recipients,
            start_tls=settings.security == "starttls",
            use_tls=settings.security == "ssl",
            validate_certs=settings.verify_tls,
            username=username,
            password=password,
            timeout=SMTP_TIMEOUT_SECONDS,
        )
    except (aiosmtplib.SMTPException, OSError) as exc:
        error = _failure(settings, exc)
        logger.warning("%s", error)
        raise error from exc


async def check_connection(
    settings: MailSettings, *, username: str | None, password: str | None
) -> None:
    """Connect, upgrade and authenticate as a real send would, then disconnect. Sends nothing."""
    _require_configured(settings)
    client = aiosmtplib.SMTP(
        hostname=settings.smtp_server,
        port=settings.smtp_port,
        start_tls=settings.security == "starttls",
        use_tls=settings.security == "ssl",
        validate_certs=settings.verify_tls,
        timeout=SMTP_TIMEOUT_SECONDS,
    )
    try:
        async with client:
            if username is not None and password is not None:
                await client.login(username, password)
            await client.noop()
    except (aiosmtplib.SMTPException, OSError) as exc:
        error = _failure(settings, exc)
        logger.warning("%s", error)
        raise error from exc
