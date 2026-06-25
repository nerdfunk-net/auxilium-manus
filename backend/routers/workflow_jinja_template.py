"""Jinja template editor APIs for workflow steps."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.jinja_template import (
    JinjaPreviewRequest,
    JinjaPreviewResponse,
    JinjaSampleContextFromDeviceRequest,
    JinjaSampleContextFromNautobotRequest,
    JinjaSampleContextResponse,
    JinjaValidateRequest,
    JinjaValidateResponse,
)
from workflow_steps.common.jinja_render import JinjaTemplateError, render_jinja_template, validate_jinja_template
from workflow_steps.common.jinja_sample_context import (
    build_sample_context_from_device_payload,
    build_sample_context_from_nautobot,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps/render-jinja-template",
    tags=["workflow-steps"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/validate", response_model=JinjaValidateResponse)
async def validate_template(
    request: JinjaValidateRequest,
    _: User = Depends(get_current_user),
) -> JinjaValidateResponse:
    try:
        validate_jinja_template(request.template)
    except JinjaTemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return JinjaValidateResponse(valid=True)


@router.post("/preview", response_model=JinjaPreviewResponse)
async def preview_template(
    request: JinjaPreviewRequest,
    _: User = Depends(get_current_user),
) -> JinjaPreviewResponse:
    try:
        rendered = render_jinja_template(request.template, request.context)
    except JinjaTemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return JinjaPreviewResponse(rendered=rendered)


@router.post("/sample-context/nautobot", response_model=JinjaSampleContextResponse)
async def sample_context_from_nautobot(
    request: JinjaSampleContextFromNautobotRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> JinjaSampleContextResponse:
    try:
        context = await build_sample_context_from_nautobot(
            db=db,
            nautobot_source_id=request.nautobot_source_id.strip(),
            device_name=request.device_name.strip(),
            list_of_attributes=request.list_of_attributes,
        )
        return JinjaSampleContextResponse(context=context)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to build Nautobot sample context: ", exc)


@router.post("/sample-context/device", response_model=JinjaSampleContextResponse)
async def sample_context_from_device(
    request: JinjaSampleContextFromDeviceRequest,
    _: User = Depends(get_current_user),
) -> JinjaSampleContextResponse:
    try:
        context = build_sample_context_from_device_payload(request.device)
        return JinjaSampleContextResponse(context=context)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to build workflow device sample context: ", exc)
