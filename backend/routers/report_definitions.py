"""Saved reports and their stored snapshots (doc/REPORTS.md)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.rate_limit import rate_limited
from core.safe_http_errors import raise_internal_server_error
from models.mail import SendSnapshotRequest, SendSnapshotResult
from models.report_definitions import (
    ReportDefinitionCreate,
    ReportDefinitionResponse,
    ReportDefinitionSummary,
    ReportDefinitionUpdate,
    ReportSnapshotResponse,
    ReportSnapshotSummary,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
)
from services.mail.errors import (
    MailCredentialError,
    MailNotConfiguredError,
    MailRecipientNotAllowedError,
    MailSendError,
)
from services.reports.pdf_renderer import PdfRenderError, PdfTooLargeError
from services.reports.report_mailer import AttachmentTooLargeError, ReportMailer
from services.reports.report_service import (
    InvalidReportError,
    ReportNameConflictError,
    ReportNotFoundError,
    ReportService,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(get_current_user)],
)

_READ = Depends(require_permission("reports", "read"))
_WRITE = Depends(require_permission("reports", "write"))
_DELETE = Depends(require_permission("reports", "delete"))
_SEND = Depends(require_permission("reports", "send"))
# Generating runs every section's query (each can take seconds); keep one user from piling up.
_GENERATE_BUDGET = Depends(rate_limited("reports-generate", attempts=10, window_seconds=60))
# A preview starts a render process per request.
_PREVIEW_BUDGET = Depends(rate_limited("reports-template-preview", attempts=30, window_seconds=60))
_PDF_BUDGET = Depends(rate_limited("reports-pdf", attempts=20, window_seconds=60))
_SEND_BUDGET = Depends(rate_limited("reports-send", attempts=10, window_seconds=60))


def get_report_service(db: Session = Depends(get_db)) -> ReportService:
    return ReportService(db)


def get_report_mailer(db: Session = Depends(get_db)) -> ReportMailer:
    return ReportMailer(db)


def _not_found(exc: ReportNotFoundError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))


# -- definitions --------------------------------------------------------------------------------


@router.get("/definitions", response_model=list[ReportDefinitionSummary], dependencies=[_READ])
def list_definitions(
    service: ReportService = Depends(get_report_service),
) -> list[ReportDefinitionSummary]:
    return service.list_definitions()


@router.post(
    "/definitions",
    response_model=ReportDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
def create_definition(
    body: ReportDefinitionCreate,
    current_user: User = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
):
    try:
        return service.create_definition(body, actor_id=current_user.id)
    except ReportNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "A report with that name exists") from exc
    except InvalidReportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get(
    "/definitions/{definition_id}", response_model=ReportDefinitionResponse, dependencies=[_READ]
)
def get_definition(definition_id: int, service: ReportService = Depends(get_report_service)):
    try:
        return service.get_definition(definition_id)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc


@router.put(
    "/definitions/{definition_id}", response_model=ReportDefinitionResponse, dependencies=[_WRITE]
)
def update_definition(
    definition_id: int,
    body: ReportDefinitionUpdate,
    service: ReportService = Depends(get_report_service),
):
    try:
        return service.update_definition(definition_id, body)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc
    except ReportNameConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "A report with that name exists") from exc
    except InvalidReportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.delete(
    "/definitions/{definition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_DELETE],
)
def delete_definition(
    definition_id: int, service: ReportService = Depends(get_report_service)
) -> Response:
    try:
        service.delete_definition(definition_id)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/definitions/{definition_id}/generate",
    response_model=ReportSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE, _GENERATE_BUDGET],
)
def generate_snapshot(
    definition_id: int,
    current_user: User = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
):
    try:
        return service.generate(definition_id, actor_name=current_user.username)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc


# -- snapshots ----------------------------------------------------------------------------------


@router.get("/snapshots", response_model=list[ReportSnapshotSummary], dependencies=[_READ])
def list_snapshots(
    definition_id: int | None = Query(default=None),
    service: ReportService = Depends(get_report_service),
):
    return service.list_snapshots(definition_id=definition_id)


@router.get("/snapshots/{snapshot_id}", response_model=ReportSnapshotResponse, dependencies=[_READ])
def get_snapshot(snapshot_id: int, service: ReportService = Depends(get_report_service)):
    try:
        return service.get_snapshot(snapshot_id)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/snapshots/{snapshot_id}/preview-template",
    response_model=TemplatePreviewResponse,
    dependencies=[_READ, _PREVIEW_BUDGET],
)
def preview_template(
    snapshot_id: int,
    body: TemplatePreviewRequest,
    service: ReportService = Depends(get_report_service),
):
    try:
        outcome = service.preview_template(snapshot_id, body.content)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc
    return TemplatePreviewResponse(markdown=outcome.markdown, error=outcome.error)


@router.get("/snapshots/{snapshot_id}/pdf", dependencies=[_READ, _PDF_BUDGET])
def download_snapshot_pdf(snapshot_id: int, mailer: ReportMailer = Depends(get_report_mailer)):
    try:
        filename, data = mailer.pdf(snapshot_id)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc
    except (PdfTooLargeError, PdfRenderError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to render the report PDF", exc)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/snapshots/{snapshot_id}/send",
    response_model=SendSnapshotResult,
    dependencies=[_SEND, _SEND_BUDGET],
)
def send_snapshot(
    snapshot_id: int,
    body: SendSnapshotRequest,
    current_user: User = Depends(get_current_user),
    mailer: ReportMailer = Depends(get_report_mailer),
):
    try:
        return mailer.send(snapshot_id, body, actor_id=current_user.id)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc
    except MailNotConfiguredError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MailCredentialError as exc:
        # The credential's name and the lookup error are for administrators (settings page, logs).
        logger.warning("Mail login unusable: %s", exc)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The mail login is not usable. Ask an administrator to check the mail settings.",
        ) from exc
    except MailRecipientNotAllowedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except (PdfTooLargeError, PdfRenderError, AttachmentTooLargeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except MailSendError as exc:
        # str(exc) names the mail host and port; it is already logged, and only the test endpoint
        # (administrators) shows it.
        logger.warning("Sending a report failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The mail server could not be reached or refused the message. "
            "Ask an administrator to check the mail settings.",
        ) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to send the report", exc)


@router.delete(
    "/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_DELETE]
)
def delete_snapshot(snapshot_id: int, service: ReportService = Depends(get_report_service)):
    try:
        service.delete_snapshot(snapshot_id)
    except ReportNotFoundError as exc:
        raise _not_found(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
