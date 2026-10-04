"""Strip shared secrets from ISE ERS payloads before they leave the backend.

ISE returns ``tacacsSettings.sharedSecret`` and ``authenticationSettings.radiusSharedSecret``
in clear text on ``GET /networkdevice/{id}``, and echoes old/new values of changed fields in
the ``UpdatedFieldsList`` of a PUT response. Workflow steps need the raw values (they seal them
into attribute bags); HTTP clients of this backend never do.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "***REDACTED***"

# Key names seen in the ERS NetworkDevice schema: sharedSecret, radiusSharedSecret,
# secondRadiusSharedSecret, previousSharedSecret, roCommunity, authPassword, privacyPassword,
# encryptionKey, authenticationKey, messageAuthenticatorCodeKey, sgaDevicePassword.
_SECRET_KEY = re.compile(
    r"(secret|password|community|encryptionkey|authenticationkey|messageauthenticatorcodekey)",
    re.IGNORECASE,
)
_CHANGED_VALUE_KEYS = frozenset({"oldValue", "newValue"})


def _is_secret_key(key: Any) -> bool:
    return isinstance(key, str) and _SECRET_KEY.search(key) is not None


def _has_value(value: Any) -> bool:
    return isinstance(value, (str, int)) and not isinstance(value, bool) and value != ""


def redact_ise_secrets(payload: Any) -> Any:
    """Return a deep copy of *payload* with every secret-bearing value replaced.

    Covers nested dicts/lists and ERS ``UpdatedFieldsList`` entries of the form
    ``{"field": "tacacsSettings.sharedSecret", "oldValue": "...", "newValue": "..."}``.
    Empty values stay empty so an unset secret is still visibly unset.
    """
    if isinstance(payload, dict):
        field_is_secret = _is_secret_key(payload.get("field"))
        redacted: dict[Any, Any] = {}
        for key, value in payload.items():
            if _is_secret_key(key) and _has_value(value):
                redacted[key] = REDACTED
            elif field_is_secret and key in _CHANGED_VALUE_KEYS and _has_value(value):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_ise_secrets(value)
        return redacted
    if isinstance(payload, list):
        return [redact_ise_secrets(item) for item in payload]
    return payload
