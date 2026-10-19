"""Sanitized HTTP error payloads for server failures."""

from __future__ import annotations

import logging
import uuid
from typing import Any, NoReturn

from fastapi import HTTPException, status
from pydantic import ValidationError

INTERNAL_ERROR_MESSAGE = "An internal error occurred"
DEFAULT_CLIENT_ERROR_MESSAGE = "The request could not be processed"
_FILE_OPERATION_FAILED_MESSAGE = "The file operation failed"


def internal_error_detail(
    *, error_id: str | None = None, message: str | None = None
) -> dict[str, str]:
    eid = error_id or str(uuid.uuid4())
    return {"message": message or INTERNAL_ERROR_MESSAGE, "error_id": eid}


def raise_internal_server_error(
    logger: logging.Logger,
    log_message: str,
    exc: BaseException | None = None,
    *,
    extra: dict[str, Any] | None = None,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    public_message: str | None = None,
) -> NoReturn:
    """``public_message`` must be a fixed string written in code, never exception text."""
    error_id = str(uuid.uuid4())
    log_extra: dict[str, Any] = {"error_id": error_id}
    if extra:
        log_extra.update(extra)
    if exc is not None:
        logger.error(
            "%s (error_id=%s)",
            log_message,
            error_id,
            exc_info=True,
            extra=log_extra,
        )
    else:
        logger.error(
            "%s (error_id=%s)",
            log_message,
            error_id,
            extra=log_extra,
        )
    raise HTTPException(
        status_code=status_code,
        detail=internal_error_detail(error_id=error_id, message=public_message),
    ) from exc


def client_error_message(
    exc: BaseException, *, fallback: str = DEFAULT_CLIENT_ERROR_MESSAGE
) -> str:
    """Text for a 4xx ``detail`` built from a caught *built-in* exception.

    A ``ValueError`` raised by our own code carries a message written for the user and is passed
    through. Two kinds of built-in exception carry library text and are reduced instead:

    - pydantic's ``ValidationError`` (a ``ValueError``): its text names model classes, echoes the
      input values and links to pydantic's docs; only ``field: rule`` is kept.
    - an ``OSError`` raised by the operating system (it has an ``errno`` or a ``filename``): its
      text includes the server-side path. One raised with a single message (neither set) keeps it.

    Exceptions of our own domain types may keep using ``str(exc)``; the guard
    ``scripts/check_http_4xx_leaks.py`` covers the built-in ones.
    """
    if isinstance(exc, ValidationError):
        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False, include_context=False)
        )
        return problems or fallback
    if isinstance(exc, OSError) and (
        exc.errno is not None or exc.filename is not None or exc.filename2 is not None
    ):
        return _FILE_OPERATION_FAILED_MESSAGE
    return str(exc).strip() or fallback
