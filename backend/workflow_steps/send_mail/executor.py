"""Executor for the send-mail step.

Sends one email per step execution through an SMTP server. Connection
settings (server, port, security protocol) live in the step config; the SMTP
username and password never do -- they come from a vault credential referenced
by name (``credential_reference``), so the canvas JSON holds no secret. Only
``generic`` credentials resolve (an ``ssh`` device password is never sent to the
configured SMTP host), and authentication is refused with ``security: none``. A
blank ``credential_reference`` sends without authentication.

``security`` selects the transport: ``none`` (plain SMTP, usually port 25),
``starttls`` (upgrade a plain connection, usually port 587) or ``ssl``
(implicit TLS from the first byte, usually port 465). ``verify_tls`` (default
true) checks the server certificate for the two TLS modes; set it to false only
for a server with a self-signed certificate, e.g. a local Proton Mail Bridge.

``subject``, ``to`` and ``from_address`` support ``{path.to.value}``
placeholders resolved against the first device in context; ``body`` renders
once per device and the results are newline-joined, like ``notify-mattermost``.
``{devices}`` / ``{device_count}`` are available everywhere. When a template
needs a device but ``context.devices`` is empty (e.g. wired to an outcome that
matched nothing) the step skips sending rather than mailing an unresolved
placeholder.

Outcomes: ``failure`` (context unchanged) when the SMTP exchange itself fails.
Bad configuration raises ``ValueError``. The failure summary and logs carry
only the exception class and SMTP status code -- never server text, which may
echo credentials.
"""

from __future__ import annotations

import logging
import re
from email.message import EmailMessage
from email.utils import parseaddr
from typing import TYPE_CHECKING, Any

import aiosmtplib
from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.credential_resolver import resolve_generic_only_credential
from workflow_steps.common.run_message_template import (
    render_for_all_devices,
    render_for_first_device,
)
from workflow_steps.send_mail.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "send-mail"
_SECURITY_MODES = frozenset({"none", "starttls", "ssl"})
_SMTP_TIMEOUT_SECONDS = 30.0
_RECIPIENT_SPLIT = re.compile(r"[,;]")
_BARE_ADDRESS = re.compile(r"^[^@\s<>,;]+@[^@\s<>,;]+$")


def _required_text(config: dict[str, Any], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise ValueError(f"{_STEP_ID}: {key} is not configured")
    return value


def _parse_port(raw: Any) -> int:
    if isinstance(raw, bool) or raw is None:
        raise ValueError(f"{_STEP_ID}: smtp_port must be a number between 1 and 65535")
    try:
        port = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"{_STEP_ID}: smtp_port must be a number between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{_STEP_ID}: smtp_port must be a number between 1 and 65535")
    return port


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


def _failure_summary(server: str, port: int, exc: Exception) -> str:
    code = getattr(exc, "code", None)
    suffix = f" (SMTP {code})" if code is not None else ""
    return f"could not send mail via {server}:{port}: {type(exc).__name__}{suffix}"


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

    defaults = get_config()
    server = _required_text(config, "smtp_server")
    port = _parse_port(config.get("smtp_port", defaults["smtp_port"]))
    security = str(config.get("security") or defaults["security"]).strip().lower()
    if security not in _SECURITY_MODES:
        raise ValueError(f"{_STEP_ID}: security must be one of none, starttls, ssl")
    # Only an explicit ``False`` turns verification off, so config saved before this
    # option existed (key absent) keeps the secure default.
    verify_tls = config.get("verify_tls") is not False
    credential_reference = str(config.get("credential_reference") or "").strip()
    if credential_reference and security == "none":
        # AUTH PLAIN/LOGIN only base64-encode the password; never put it on a cleartext link.
        raise ValueError(
            f"{_STEP_ID}: credential_reference requires security starttls or ssl "
            "(refusing to send the SMTP password unencrypted)"
        )
    from_template = _required_text(config, "from_address")
    to_template = _required_text(config, "to")
    subject_template = _required_text(config, "subject")
    body_template = _required_text(config, "body")

    from_rendered = render_for_first_device(from_template, context)
    to_rendered = render_for_first_device(to_template, context)
    subject = render_for_first_device(subject_template, context)
    body = render_for_all_devices(body_template, context)
    if from_rendered is None or to_rendered is None or subject is None or body is None:
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

    for label, value in (
        ("from_address", from_rendered),
        ("to", to_rendered),
        ("subject", subject),
    ):
        _reject_header_breaks(label, value)
    sender = _bare_address("from_address", from_rendered)
    recipients = _parse_recipients(to_rendered)

    username: str | None = None
    password: str | None = None
    if credential_reference:
        db = object_session(run)
        if db is None:
            raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
        username, password = resolve_generic_only_credential(
            db, credential_reference, acting_user_id=run.triggered_by_id
        )

    message = EmailMessage()
    message["From"] = from_rendered.strip()
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject.strip()
    message.set_content(body)

    logger.info(
        "%s started run_id=%s node_id=%s server=%s port=%d security=%s verify_tls=%s recipients=%d",
        _STEP_ID,
        context.run_id,
        node_id,
        server,
        port,
        security,
        verify_tls,
        len(recipients),
    )

    try:
        await aiosmtplib.send(
            message,
            hostname=server,
            port=port,
            sender=sender,
            recipients=recipients,
            start_tls=security == "starttls",
            use_tls=security == "ssl",
            validate_certs=verify_tls,
            username=username,
            password=password,
            timeout=_SMTP_TIMEOUT_SECONDS,
        )
    except (aiosmtplib.SMTPException, OSError) as exc:
        summary = _failure_summary(server, port, exc)
        logger.warning("%s: %s node_id=%s run_id=%s", _STEP_ID, summary, node_id, context.run_id)
        return [StepOutcome(name="failure", context=context, summary=summary)]

    logger.info(
        "%s finished node_id=%s server=%s recipients=%d run_id=%s",
        _STEP_ID,
        node_id,
        server,
        len(recipients),
        context.run_id,
    )

    return [
        StepOutcome(
            name="success",
            context=context,
            summary=f"sent to {len(recipients)} recipient(s) via {server}:{port}",
        )
    ]
