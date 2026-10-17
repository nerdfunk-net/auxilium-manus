"""Exception → HTTP mapping shared by every ISE endpoint (Q2).

Replaces the identical ``except ISENotFoundError / ISEValidationError / ISEAPIError /
HTTPException / Exception`` ladders that used to repeat in ``ops.py``.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, status

from core.safe_http_errors import raise_internal_server_error
from services.ise.common.exceptions import ISEAPIError, ISENotFoundError, ISEValidationError

logger = logging.getLogger(__name__)


def ise_errors(action: str) -> Callable[..., Callable[..., Awaitable]]:
    """Map ISE failures to 404 / 400 / sanitised 502, anything else to a sanitised 500."""

    def decorator[**P, R](fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await fn(*args, **kwargs)
            except HTTPException:
                raise
            except ISENotFoundError as exc:  # subclass of ISEAPIError: must come first
                # str(exc) names the upstream ISE endpoint path; do not echo it to the client.
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="ISE resource not found"
                ) from exc
            except ISEValidationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
                ) from exc
            except ISEAPIError as exc:
                raise_internal_server_error(
                    logger,
                    f"ISE {action} failed: ",
                    exc,
                    status_code=status.HTTP_502_BAD_GATEWAY,
                )
            except Exception as exc:
                raise_internal_server_error(logger, f"Failed to {action}: ", exc)

        return wrapper

    return decorator
