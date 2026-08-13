"""Router for the CA certificate manager (dev/admin tools)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from core.auth import get_current_user, require_permission
from core.dev_tools import require_dev_tools
from core.safe_http_errors import raise_internal_server_error
from models.certificates import (
    AddCertificateRequest,
    AddCertificateResponse,
    CertificateInfo,
    ScanResponse,
)
from services.certificates.certificate_service import CertificateService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/certificates",
    tags=["certificates"],
    dependencies=[Depends(get_current_user)],
)


def _service() -> CertificateService:
    return CertificateService()


@router.get(
    "/scan",
    response_model=ScanResponse,
    dependencies=[Depends(require_permission("system.certificates", "read"))],
)
async def scan_certificates(
    service: CertificateService = Depends(_service),
) -> ScanResponse:
    return service.scan()


@router.post(
    "/upload",
    response_model=CertificateInfo,
    dependencies=[Depends(require_permission("system.certificates", "write"))],
)
async def upload_certificate(
    file: UploadFile = File(...),
    service: CertificateService = Depends(_service),
) -> CertificateInfo:
    try:
        return await service.upload(file)
    except FileExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OSError as exc:
        raise_internal_server_error(logger, "Failed to store uploaded certificate", exc)


@router.post(
    "/add-to-system",
    response_model=AddCertificateResponse,
    dependencies=[
        Depends(require_dev_tools),
        Depends(require_permission("system.certificates", "write")),
    ],
)
async def add_certificate_to_system(
    body: AddCertificateRequest,
    service: CertificateService = Depends(_service),
) -> AddCertificateResponse:
    try:
        return service.add_to_system(body.filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete(
    "/{filename}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("system.certificates", "write"))],
)
async def delete_certificate(
    filename: str,
    service: CertificateService = Depends(_service),
) -> None:
    try:
        service.delete(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
