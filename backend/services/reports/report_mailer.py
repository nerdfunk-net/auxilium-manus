"""Send a stored report snapshot by email, or export it as PDF (doc/REPORTS.md).

Both start from the Markdown stored in the snapshot (``content.body.markdown``). A snapshot whose
text could not be rendered (older snapshots, a broken template) falls back to the default template
rendered from the stored section data, so there is always something to send.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from sqlalchemy.orm import Session

from models.mail import SendSnapshotRequest, SendSnapshotResult
from models.report_definitions import SnapshotContent
from services.mail.errors import MailError, MailRecipientNotAllowedError
from services.mail.mail_service import MailService
from services.mail.recipients import disallowed_recipients
from services.reports.pdf_renderer import render_pdf
from services.reports.report_html import markdown_to_email_html
from services.reports.report_renderer import DEFAULT_TEMPLATE
from services.reports.report_service import ReportService

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class AttachmentTooLargeError(MailError):
    """The PDF would exceed the attachment limit."""


def pdf_filename(name: str) -> str:
    """An ASCII file name for the PDF, derived from the snapshot name."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stem = re.sub(r"-{2,}", "-", _FILENAME_SAFE.sub("-", ascii_name)).strip("-.")[:80] or "report"
    return f"{stem}.pdf"


class ReportMailer:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.reports = ReportService(db)

    def _markdown(self, snapshot_id: int) -> tuple[str, str]:
        """``(snapshot name, markdown)``; raises ``ReportNotFoundError``."""
        snapshot = self.reports.get_snapshot(snapshot_id)
        body = SnapshotContent.model_validate(snapshot.content).body
        if body is not None and body.markdown:
            return snapshot.name, body.markdown
        fallback = self.reports.preview_template(snapshot_id, DEFAULT_TEMPLATE)
        return snapshot.name, fallback.markdown or f"# {snapshot.name}\n"

    def pdf(self, snapshot_id: int) -> tuple[str, bytes]:
        """``(file name, PDF bytes)`` of the snapshot's report text."""
        name, markdown = self._markdown(snapshot_id)
        return pdf_filename(name), render_pdf(title=name, markdown=markdown)

    def send(
        self, snapshot_id: int, request: SendSnapshotRequest, *, actor_id: int | None
    ) -> SendSnapshotResult:
        mail = MailService(self.db)
        allowed = mail.settings().allowed_recipient_domains
        blocked = disallowed_recipients(request.to, allowed)
        if blocked:
            raise MailRecipientNotAllowedError(
                f"Not allowed as recipient: {', '.join(blocked)}. "
                f"Allowed domains: {', '.join(allowed)}"
            )
        name, markdown = self._markdown(snapshot_id)
        attachments: list[tuple[str, bytes]] = []
        if request.include_pdf:
            data = render_pdf(title=name, markdown=markdown)
            if len(data) > MAX_ATTACHMENT_BYTES:
                raise AttachmentTooLargeError(
                    "The PDF is too large to attach; send without the PDF attachment"
                )
            attachments.append((pdf_filename(name), data))
        text = f"{request.message}\n\n{markdown}" if request.message else markdown
        mail.send(
            recipients=request.to,
            subject=request.subject or " ".join(name.split()),
            text=text,
            html=markdown_to_email_html(markdown, intro=request.message),
            attachments=attachments,
        )
        domains = sorted({address.rsplit("@", 1)[-1].lower() for address in request.to})
        # Who sent what where, without the addresses themselves.
        logger.info(
            "Report snapshot %s sent by user %s to %d recipient(s) at %s (pdf=%s)",
            snapshot_id,
            actor_id,
            len(request.to),
            ", ".join(domains),
            bool(attachments),
        )
        return SendSnapshotResult(sent_to=request.to, pdf_attached=bool(attachments))
