"""Encrypt / Decrypt Attribute step editor APIs.

Crypto calculator used by the steps' "Test Encryption" / "Test Decryption"
modals. The caller supplies the value plus either a literal shared secret or a
``credential_reference`` naming a ``shared_secret`` vault credential (resolved
the same way the step itself resolves it at run time, scoped to the acting
user via ``CredentialManager``). Neither path echoes the passphrase back to
the client, so ``workflow_steps:read`` remains the appropriate guard (matching
the update-attribute probe router).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.passphrase_cipher import (
    PassphraseCipherError,
    algorithm_of_token,
    decrypt_with_passphrase,
    encrypt_with_passphrase,
    normalize_algorithm,
)
from core.safe_http_errors import raise_internal_server_error
from models.crypto_attribute import (
    DecryptAttributeTestRequest,
    DecryptAttributeTestResponse,
    EncryptAttributeTestRequest,
    EncryptAttributeTestResponse,
)
from workflow_steps.common.credential_resolver import (
    CredentialReferenceInvalidError,
    CredentialReferenceNotFoundError,
    resolve_shared_secret_credential,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps",
    tags=["workflow-steps"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("workflow_steps", "read")),
    ],
)


def _resolve_passphrase(
    db: Session,
    current_user: User,
    *,
    shared_secret: str | None,
    credential_reference: str | None,
) -> tuple[str, str | None]:
    """Return ``(passphrase, credential_algorithm)``. ``credential_algorithm``
    is ``None`` when the caller typed the secret inline."""
    if credential_reference:
        try:
            cred_algorithm, passphrase = resolve_shared_secret_credential(
                db, credential_reference, acting_user_id=current_user.id
            )
        except (CredentialReferenceNotFoundError, CredentialReferenceInvalidError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        return passphrase, cred_algorithm
    if shared_secret is None:
        # Unreachable: the request model validator requires exactly one of
        # shared_secret / credential_reference to be set.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="shared_secret or credential_reference is required",
        )
    return shared_secret, None


@router.post("/encrypt-attribute/test", response_model=EncryptAttributeTestResponse)
def test_encrypt_attribute(
    request: EncryptAttributeTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EncryptAttributeTestResponse:
    try:
        passphrase, cred_algorithm = _resolve_passphrase(
            db,
            current_user,
            shared_secret=request.shared_secret,
            credential_reference=request.credential_reference,
        )
        algorithm = normalize_algorithm(request.algorithm or cred_algorithm)
        ciphertext = encrypt_with_passphrase(request.plaintext, passphrase, algorithm=algorithm)
        return EncryptAttributeTestResponse(ciphertext=ciphertext, algorithm=algorithm)
    except HTTPException:
        raise
    except PassphraseCipherError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to test encrypt-attribute: ", exc)


@router.post("/decrypt-attribute/test", response_model=DecryptAttributeTestResponse)
def test_decrypt_attribute(
    request: DecryptAttributeTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DecryptAttributeTestResponse:
    try:
        passphrase, _cred_algorithm = _resolve_passphrase(
            db,
            current_user,
            shared_secret=request.shared_secret,
            credential_reference=request.credential_reference,
        )
        # A blank override means "trust the token's own algorithm header" —
        # same as the step executor; the credential's configured algorithm is
        # only a default for *encrypting*, never used to override a decrypt.
        requested = normalize_algorithm(request.algorithm) if request.algorithm else None
        plaintext = decrypt_with_passphrase(request.ciphertext, passphrase, algorithm=requested)
        return DecryptAttributeTestResponse(
            plaintext=plaintext, algorithm=algorithm_of_token(request.ciphertext)
        )
    except HTTPException:
        raise
    except PassphraseCipherError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to test decrypt-attribute: ", exc)
