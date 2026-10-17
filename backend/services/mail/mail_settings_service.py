"""Global mail settings, stored as one Settings entry (doc/REPORTS.md, "Email and PDF")."""

from __future__ import annotations

from sqlalchemy.orm import Session

from models.mail import MailSettings, MailSettingsResponse
from repositories.settings_repository import SettingsRepository

SETTINGS_KEY = "mail.smtp"


def to_response(settings: MailSettings) -> MailSettingsResponse:
    return MailSettingsResponse(
        **settings.model_dump(),
        configured=bool(settings.smtp_server and settings.from_address),
    )


class MailSettingsService:
    def __init__(self, db: Session) -> None:
        self._repo = SettingsRepository(db)

    def load(self) -> MailSettings:
        row = self._repo.get_by_key(SETTINGS_KEY)
        if row is None:
            return MailSettings()
        return MailSettings.model_validate(row.value)

    def get(self) -> MailSettingsResponse:
        return to_response(self.load())

    def update(self, settings: MailSettings) -> MailSettingsResponse:
        row = self._repo.get_by_key(SETTINGS_KEY)
        value = settings.model_dump()
        if row is None:
            self._repo.create(key=SETTINGS_KEY, value=value, description="Global SMTP settings")
        else:
            self._repo.update(row, {"value": value})
        return to_response(settings)
