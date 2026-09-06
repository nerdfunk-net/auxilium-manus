"""Encrypt / Decrypt Attribute step editor APIs.

Stateless crypto calculator used by the steps' "Test Encryption" /
"Test Decryption" modals. The caller supplies both the value and the shared
secret, so this reveals no stored vault secret — ``workflow_steps:read`` is the
appropriate guard (matching the update-attribute probe router).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
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

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps",
    tags=["workflow-steps"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("workflow_steps", "read")),
    ],
)


@router.post("/encrypt-attribute/test", response_model=EncryptAttributeTestResponse)
def test_encrypt_attribute(
    request: EncryptAttributeTestRequest,
    _: User = Depends(get_current_user),
) -> EncryptAttributeTestResponse:
    try:
        algorithm = normalize_algorithm(request.algorithm)
        ciphertext = encrypt_with_passphrase(
            request.plaintext, request.shared_secret, algorithm=algorithm
        )
        return EncryptAttributeTestResponse(ciphertext=ciphertext, algorithm=algorithm)
    except PassphraseCipherError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to test encrypt-attribute: ", exc)


@router.post("/decrypt-attribute/test", response_model=DecryptAttributeTestResponse)
def test_decrypt_attribute(
    request: DecryptAttributeTestRequest,
    _: User = Depends(get_current_user),
) -> DecryptAttributeTestResponse:
    try:
        requested = normalize_algorithm(request.algorithm) if request.algorithm else None
        plaintext = decrypt_with_passphrase(
            request.ciphertext, request.shared_secret, algorithm=requested
        )
        return DecryptAttributeTestResponse(
            plaintext=plaintext, algorithm=algorithm_of_token(request.ciphertext)
        )
    except PassphraseCipherError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to test decrypt-attribute: ", exc)
