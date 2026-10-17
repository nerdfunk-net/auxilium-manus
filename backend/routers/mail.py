"""Global mail (SMTP) settings (doc/REPORTS.md, "Email and PDF")."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.rate_limit import rate_limited
from core.safe_http_errors import raise_internal_server_error
from models.mail import MailSettings, MailSettingsResponse, MailTestResult
from services.mail.errors import MailCredentialError, MailError
from services.mail.mail_service import MailService
from services.mail.mail_settings_service import MailSettingsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mail", tags=["mail"], dependencies=[Depends(get_current_user)])

# A test opens a connection to the configured server.
_TEST_BUDGET = Depends(rate_limited("mail-test", attempts=6, window_seconds=60))


@router.get(
    "/settings",
    response_model=MailSettingsResponse,
    dependencies=[Depends(require_permission("system.mail", "read"))],
)
def get_mail_settings(db: Session = Depends(get_db)) -> MailSettingsResponse:
    return MailSettingsService(db).get()


@router.put(
    "/settings",
    response_model=MailSettingsResponse,
    dependencies=[Depends(require_permission("system.mail", "write"))],
)
def update_mail_settings(body: MailSettings, db: Session = Depends(get_db)) -> MailSettingsResponse:
    try:
        # The credential must exist and be global, so the problem shows up here, not at send time.
        MailService(db).check_credential(body)
    except MailCredentialError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return MailSettingsService(db).update(body)


@router.post(
    "/settings/test",
    response_model=MailTestResult,
    dependencies=[Depends(require_permission("system.mail", "write")), _TEST_BUDGET],
)
def test_mail_settings(db: Session = Depends(get_db)) -> MailTestResult:
    """Connect and authenticate with the saved settings; nothing is sent."""
    try:
        MailService(db).check_connection()
    except MailError as exc:
        return MailTestResult(ok=False, message=str(exc))
    except Exception as exc:
        raise_internal_server_error(logger, "Mail connection test failed", exc)
    return MailTestResult(ok=True, message="Connected and authenticated")
