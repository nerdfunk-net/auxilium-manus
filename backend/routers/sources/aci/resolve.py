"""Resolve a saved Cisco ACI source to credentials for a route, mapping errors to HTTP statuses."""

from __future__ import annotations

from fastapi import HTTPException, status

from core.safe_urls import UnsafeURLError
from core.source_keys import SOURCE_ID_PATTERN
from services.aci.common.exceptions import AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.source_config_service import AciSourceConfigService, AciSourceNotFoundError
from services.credentials.source_credentials import SourceCredentialError


def resolve_saved_credentials(source_id: str, config: AciSourceConfigService) -> AciCredentials:
    """Credentials of the saved source ``source_id``.

    A malformed id (anything ``build_source_key`` would reject) is a 400 before the config service
    is called: the service raises a bare ``ValueError`` for it, which would otherwise surface as an
    unhandled 500. The same normalisation (strip, lower-case) as the key builder is applied.
    """
    if not SOURCE_ID_PATTERN.fullmatch(source_id.strip().lower()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid source id")
    try:
        return config.resolve_credentials(source_id)
    except AciSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (AciValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
