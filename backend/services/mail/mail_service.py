"""Sending mail through the global SMTP settings, from synchronous code (worker threads).

The password comes from the global ``generic`` credential named in the settings: only global
credentials resolve (``acting_user_id=None``), so a user's private credential can never be used by
somebody else's mail.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from sqlalchemy.orm import Session

from models.mail import MailSettings
from services.credentials.manager import CredentialManager
from services.credentials.secrets import CredentialLookupError, CredentialUnusableError
from services.mail import smtp_sender
from services.mail.errors import MailCredentialError
from services.mail.mail_settings_service import MailSettingsService


class MailService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def settings(self) -> MailSettings:
        return MailSettingsService(self.db).load()

    def connection(self) -> tuple[MailSettings, str | None, str | None]:
        """The global settings plus the global credential's username and password (S3-02)."""
        settings = self.settings()
        username, password = self._credentials(settings)
        return settings, username, password

    def check_credential(self, settings: MailSettings) -> None:
        """Raise ``MailCredentialError`` unless the named credential is a usable global one."""
        self._credentials(settings)

    def _credentials(self, settings: MailSettings) -> tuple[str | None, str | None]:
        if not settings.credential_name:
            return None, None
        try:
            secret = CredentialManager(self.db, acting_user_id=None).generic_only(
                settings.credential_name
            )
        except (CredentialLookupError, CredentialUnusableError) as exc:
            raise MailCredentialError(str(exc)) from exc
        return secret.username, secret.password

    def check_connection(self) -> None:
        settings = self.settings()
        username, password = self._credentials(settings)
        asyncio.run(smtp_sender.check_connection(settings, username=username, password=password))

    def send(
        self,
        *,
        recipients: Sequence[str],
        subject: str,
        text: str,
        html: str | None = None,
        attachments: Sequence[tuple[str, bytes]] = (),
    ) -> None:
        settings = self.settings()
        username, password = self._credentials(settings)
        message = smtp_sender.build_message(
            sender=settings.from_address,
            recipients=recipients,
            subject=subject,
            text=text,
            html=html,
            attachments=attachments,
        )
        asyncio.run(
            smtp_sender.send_message(settings, message, username=username, password=password)
        )
