"""Exact-match secrets for the assistant's redactor (S5-04).

Pattern redaction misses a bare password on a line of its own. When the user shares run or device
content, the values of the credentials they can resolve are registered with the request's
``Redactor`` so those exact strings become tokens wherever they occur.
"""

from __future__ import annotations

import logging

from core.database import SessionLocal
from services.credentials.credentials_service import CredentialsService

logger = logging.getLogger(__name__)

MAX_KNOWN_CREDENTIALS = 200


def load_visible_secret_values(user_id: int) -> list[str]:
    """Decrypted passwords / tokens of the credentials ``user_id`` can see (never raises)."""
    try:
        with SessionLocal() as db:
            return CredentialsService(db).visible_secret_values(
                user_id, limit=MAX_KNOWN_CREDENTIALS
            )
    except Exception:
        logger.warning("could not load credential values for assistant redaction", exc_info=True)
        return []
