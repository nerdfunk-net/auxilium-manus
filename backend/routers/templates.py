from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.templates import (
    TemplateCreate,
    TemplateListResponse,
    TemplateRenderRequest,
    TemplateRenderResponse,
    TemplateResponse,
    TemplateUpdate,
)
from services.templates.exceptions import (
    TemplateNameConflictError,
    TemplateNotFoundError,
)
from services.templates.templates_service import TemplatesService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/templates",
    tags=["templates"],
    dependencies=[Depends(get_current_user)],
)


def _service(db: Session = Depends(get_db)) -> TemplatesService:
    return TemplatesService(db)


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    category: str | None = Query(None),
    search: str | None = Query(None),
    _current_user: User = Depends(get_current_user),
    service: TemplatesService = Depends(_service),
) -> TemplateListResponse:
    templates = service.list_templates(category=category, search=search)
    return TemplateListResponse(templates=templates, total=len(templates))


@router.get("/categories", response_model=list[str])
async def list_categories(
    _current_user: User = Depends(get_current_user),
    service: TemplatesService = Depends(_service),
) -> list[str]:
    return service.list_categories()


@router.post("/render", response_model=TemplateRenderResponse)
async def render_template(
    payload: TemplateRenderRequest,
    _current_user: User = Depends(get_current_user),
    service: TemplatesService = Depends(_service),
) -> TemplateRenderResponse:
    try:
        result = service.render(
            template_content=payload.template_content,
            variables=payload.variables,
        )
        return TemplateRenderResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to render template", exc)


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: int,
    _current_user: User = Depends(get_current_user),
    service: TemplatesService = Depends(_service),
) -> TemplateResponse:
    try:
        return TemplateResponse.model_validate(service.get_template(template_id))
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to fetch template", exc)


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate,
    current_user: User = Depends(get_current_user),
    service: TemplatesService = Depends(_service),
) -> TemplateResponse:
    try:
        result = service.create_template(
            name=payload.name,
            description=payload.description,
            template_type=payload.template_type,
            category=payload.category,
            content=payload.content,
            variables={key: value.model_dump() for key, value in payload.variables.items()},
            pre_run_command=payload.pre_run_command,
            credential_id=payload.credential_id,
            created_by=current_user.username,
        )
        return TemplateResponse.model_validate(result)
    except TemplateNameConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create template", exc)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    _current_user: User = Depends(get_current_user),
    service: TemplatesService = Depends(_service),
) -> TemplateResponse:
    try:
        variables = (
            {key: value.model_dump() for key, value in payload.variables.items()}
            if payload.variables is not None
            else None
        )
        result = service.update_template(
            template_id,
            name=payload.name,
            description=payload.description,
            template_type=payload.template_type,
            category=payload.category,
            content=payload.content,
            variables=variables,
            pre_run_command=payload.pre_run_command,
            credential_id=payload.credential_id,
        )
        return TemplateResponse.model_validate(result)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except TemplateNameConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update template", exc)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: int,
    hard_delete: bool = Query(True),
    _current_user: User = Depends(get_current_user),
    service: TemplatesService = Depends(_service),
) -> None:
    try:
        service.delete_template(template_id, hard_delete=hard_delete)
    except TemplateNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete template", exc)
