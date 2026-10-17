"""Executor for the send-mail step.

Sends one email per step execution through the SMTP server an administrator configured under
Settings -> Mail (the same global settings, credential and ``allowed_recipient_domains`` the
report mailer uses). The step config carries only recipients, subject and body: a workflow
author cannot choose the server, the port, the transport security, the credential or the sender
address, so the step has no SSRF surface, no credential can be redirected to a host of the
author's choice, and the admin's recipient-domain allow-list applies.

``subject`` and ``to`` support ``{path.to.value}`` placeholders resolved against the first
device in context; ``body`` renders once per device and the results are newline-joined, like
``notify-mattermost``. ``{devices}`` / ``{device_count}`` are available everywhere. When a
template needs a device but ``context.devices`` is empty (e.g. wired to an outcome that matched
nothing) the step skips sending rather than mailing an unresolved placeholder.

Outcomes: ``failure`` (context unchanged) when the SMTP exchange itself fails. Bad configuration
raises ``ValueError``. The failure summary and logs carry only the exception class and SMTP
status code -- never server text, which may echo credentials.
"""

from __future__ import annotations

import logging
import re
from email.utils import parseaddr
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.mail import smtp_sender
from services.mail.errors import MailCredentialError, MailSendError
from services.mail.mail_service import MailService
from services.mail.recipients import disallowed_recipients
from workflow_steps.common.run_message_template import (
    render_for_all_devices,
    render_for_first_device,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "send-mail"
_RECIPIENT_SPLIT = re.compile(r"[,;]")
_BARE_ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+$")


def _required_text(config: dict[str, Any], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise ValueError(f"{_STEP_ID}: {key} is not configured")
    return value


def _reject_header_breaks(label: str, value: str) -> None:
    """Refuse CR/LF in a header value so a resolved attribute can't inject headers."""
    if "\r" in value or "\n" in value:
        raise ValueError(f"{_STEP_ID}: {label} must be a single line")


def _bare_address(label: str, value: str) -> str:
    address = parseaddr(value)[1]
    if not _BARE_ADDRESS.match(address):
        raise ValueError(f"{_STEP_ID}: {label} '{value}' is not a valid email address")
    return address


def _parse_recipients(rendered_to: str) -> list[str]:
    entries = [entry.strip() for entry in _RECIPIENT_SPLIT.split(rendered_to) if entry.strip()]
    if not entries:
        raise ValueError(f"{_STEP_ID}: to resolved to no recipients")
    return [_bare_address("to", entry) for entry in entries]


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions

    to_template = _required_text(config, "to")
    subject_template = _required_text(config, "subject")
    body_template = _required_text(config, "body")

    to_rendered = render_for_first_device(to_template, context)
    subject = render_for_first_device(subject_template, context)
    body = render_for_all_devices(body_template, context)
    if to_rendered is None or subject is None or body is None:
        logger.info(
            "%s skipped node_id=%s run_id=%s: no devices to report",
            _STEP_ID,
            node_id,
            context.run_id,
        )
        return [
            StepOutcome(
                name="success",
                context=context,
                summary="skipped: no devices to report",
            )
        ]

    for label, value in (("to", to_rendered), ("subject", subject)):
        _reject_header_breaks(label, value)
    recipients = _parse_recipients(to_rendered)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
    try:
        # MailService reads the global settings and resolves the global credential
        # (acting_user_id=None: a user's private credential is never used here).
        connection, username, password = MailService(db).connection()
    except MailCredentialError as exc:
        raise ValueError(f"{_STEP_ID}: the mail settings' credential is not usable") from exc
    if not connection.smtp_server or not connection.from_address:
        raise ValueError(
            f"{_STEP_ID}: mail is not configured; an administrator must set it up under "
            "Settings -> Mail"
        )
    blocked = disallowed_recipients(recipients, connection.allowed_recipient_domains)
    if blocked:
        raise ValueError(
            f"{_STEP_ID}: recipient domain not allowed by the mail settings: {', '.join(blocked)}"
        )
    message = smtp_sender.build_message(
        sender=connection.from_address,
        recipients=recipients,
        subject=subject.strip(),
        text=body,
    )

    logger.info(
        "%s started run_id=%s node_id=%s recipients=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        len(recipients),
    )

    try:
        await smtp_sender.send_message(connection, message, username=username, password=password)
    except MailSendError as exc:
        summary = str(exc)
        logger.warning("%s: %s node_id=%s run_id=%s", _STEP_ID, summary, node_id, context.run_id)
        return [StepOutcome(name="failure", context=context, summary=summary)]

    logger.info(
        "%s finished node_id=%s recipients=%d run_id=%s",
        _STEP_ID,
        node_id,
        len(recipients),
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context,
            summary=f"sent to {len(recipients)} recipient(s)",
        )
    ]
