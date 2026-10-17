"""Factory for the five identical ``/sources/<type>`` CRUD routers.

Test-connection and the ops routes stay in each source's own module; only the CRUD ladder is shared.
Handlers are plain ``def`` (the services use a synchronous DB session), so FastAPI runs them in its
threadpool instead of blocking the event loop.

Do not add ``from __future__ import annotations`` here: FastAPI resolves the handler annotations
(``request: create_model``) from the enclosing scope at definition time; string annotations would
not resolve.
"""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error

logger = logging.getLogger(__name__)


def build_source_crud_router(
    *,
    source_type: str,
    display_name: str,
    permission_resource: str,
    tag: str,
    service_dependency: Callable[..., Any],
    create_model: type[BaseModel],
    update_model: type[BaseModel],
    response_model: type[BaseModel],
    list_response_model: type[BaseModel],
    not_found_error: type[Exception],
    conflict_error: type[Exception],
    validation_errors: tuple[type[Exception], ...],
    create_kwargs: Callable[[Any], dict[str, Any]],
    update_kwargs: Callable[[Any], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(
        prefix=f"/sources/{source_type}",
        tags=[tag],
        dependencies=[Depends(require_permission(permission_resource, "read"))],
    )
    bad_request: tuple[type[Exception], ...] = (*validation_errors, ValueError)
    write = Depends(require_permission(permission_resource, "write"))
    delete = Depends(require_permission(permission_resource, "delete"))

    @router.get("", response_model=list_response_model, name=f"list_{source_type}_sources")
    def list_sources(_: User = Depends(get_current_user), service=Depends(service_dependency)):
        try:
            sources = service.list_sources()
            return list_response_model(
                sources=[response_model(**s) for s in sources], total=len(sources)
            )
        except Exception as exc:
            raise_internal_server_error(logger, f"Failed to list {display_name} sources: ", exc)

    @router.get("/{source_id}", response_model=response_model, name=f"get_{source_type}_source")
    def get_source(
        source_id: str, _: User = Depends(get_current_user), service=Depends(service_dependency)
    ):
        try:
            return response_model(**service.get_source(source_id))
        except not_found_error as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise_internal_server_error(logger, f"Failed to get {display_name} source: ", exc)

    @router.post(
        "",
        response_model=response_model,
        status_code=status.HTTP_201_CREATED,
        dependencies=[write],
        name=f"create_{source_type}_source",
    )
    def create_source(
        request: create_model,  # pyright: ignore[reportInvalidTypeForm]
        _: User = Depends(get_current_user),
        service=Depends(service_dependency),
    ):
        try:
            return response_model(**service.create_source(**create_kwargs(request)))
        except conflict_error as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except bad_request as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise_internal_server_error(logger, f"Failed to create {display_name} source: ", exc)

    @router.put(
        "/{source_id}",
        response_model=response_model,
        dependencies=[write],
        name=f"update_{source_type}_source",
    )
    def update_source(
        source_id: str,
        request: update_model,  # pyright: ignore[reportInvalidTypeForm]
        _: User = Depends(get_current_user),
        service=Depends(service_dependency),
    ):
        try:
            return response_model(**service.update_source(source_id, **update_kwargs(request)))
        except not_found_error as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except bad_request as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise_internal_server_error(logger, f"Failed to update {display_name} source: ", exc)

    @router.delete(
        "/{source_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[delete],
        name=f"delete_{source_type}_source",
    )
    def delete_source(
        source_id: str, _: User = Depends(get_current_user), service=Depends(service_dependency)
    ) -> None:
        try:
            service.delete_source(source_id)
        except not_found_error as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise_internal_server_error(logger, f"Failed to delete {display_name} source: ", exc)

    return router
