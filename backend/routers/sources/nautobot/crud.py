"""CRUD for saved Nautobot source inventories."""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_inventory_service
from models.sources_nautobot import (
    CreateInventoryRequest,
    ImportInventoryRequest,
    InventoryDeleteResponse,
    InventoryResponse,
    ListInventoriesResponse,
    UpdateInventoryRequest,
)
from services.sources.nautobot.persistence_service import InventoryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sources/nautobot", tags=["sources-nautobot"])


@router.post(
    "",
    response_model=InventoryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.nautobot", "write"))],
)
async def create_inventory(
    request: CreateInventoryRequest,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> InventoryResponse:
    try:
        inventory_id = persistence.create_inventory(
            {
                "name": request.name,
                "description": request.description,
                "conditions": request.conditions,
                "template_category": request.template_category,
                "template_name": request.template_name,
                "scope": request.scope,
                "group_path": request.group_path,
                "created_by": current_user.username,
            }
        )
        if not inventory_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create inventory",
            )
        inventory = persistence.get_inventory(inventory_id)
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Inventory created but could not be retrieved",
            )
        return InventoryResponse(**inventory)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to create inventory: ", exc)


@router.get(
    "",
    response_model=ListInventoriesResponse,
    dependencies=[Depends(require_permission("sources.nautobot", "read"))],
)
async def list_inventories(
    scope: str | None = None,
    active_only: bool = True,
    group_path: str | None = None,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> ListInventoriesResponse:
    try:
        inventories = persistence.list_inventories(
            username=current_user.username,
            active_only=active_only,
            scope=scope,
            group_path_filter=group_path,
        )
        return ListInventoriesResponse(
            inventories=[InventoryResponse(**inv) for inv in inventories],
            total=len(inventories),
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list inventories: ", exc)


@router.get(
    "/search/{query}",
    response_model=ListInventoriesResponse,
    dependencies=[Depends(require_permission("sources.nautobot", "read"))],
)
async def search_inventories(
    query: str,
    active_only: bool = True,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> ListInventoriesResponse:
    try:
        inventories = persistence.search_inventories(query, current_user.username, active_only)
        return ListInventoriesResponse(
            inventories=[InventoryResponse(**inv) for inv in inventories],
            total=len(inventories),
        )
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to search inventories: ", exc)


@router.get(
    "/by-name/{inventory_name}",
    response_model=InventoryResponse,
    dependencies=[Depends(require_permission("sources.nautobot", "read"))],
)
async def get_inventory_by_name(
    inventory_name: str,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> InventoryResponse:
    try:
        inventory = persistence.get_inventory_by_name(inventory_name, current_user.username)
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inventory '{inventory_name}' not found",
            )
        return InventoryResponse(**inventory)
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get inventory: ", exc)


@router.get(
    "/export/{inventory_id}",
    dependencies=[Depends(require_permission("sources.nautobot", "read"))],
)
async def export_inventory(
    inventory_id: int,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
):
    try:
        inventory = persistence.get_inventory(inventory_id, username=current_user.username)
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inventory with ID {inventory_id} not found",
            )

        export_data = {
            "version": 2,
            "metadata": {
                "name": inventory["name"],
                "description": inventory.get("description", ""),
                "scope": inventory["scope"],
                "exportedAt": datetime.utcnow().isoformat() + "Z",
                "exportedBy": current_user.username,
                "originalId": inventory["id"],
            },
            "conditionTree": None,
        }

        conditions = inventory.get("conditions", [])
        if conditions:
            first = conditions[0]
            if isinstance(first, dict) and first.get("version") == 2:
                export_data["conditionTree"] = first.get("tree")
            else:
                export_data["conditionTree"] = {
                    "type": "root",
                    "internalLogic": "AND",
                    "items": [
                        {
                            "id": f"item-{index}",
                            "field": cond.get("field", ""),
                            "operator": cond.get("operator", ""),
                            "value": cond.get("value", ""),
                        }
                        for index, cond in enumerate(conditions)
                    ],
                }

        return JSONResponse(
            content=export_data,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="inventory-{inventory["name"]}.json"'
                )
            },
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to export inventory: ", exc)


@router.post(
    "/import",
    response_model=InventoryResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("sources.nautobot", "write"))],
)
async def import_inventory(
    request: ImportInventoryRequest,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> InventoryResponse:
    try:
        import_data = request.import_data
        if import_data.get("version") != 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid inventory file format. Expected version 2.",
            )
        if not import_data.get("conditionTree"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid inventory file. Missing condition tree.",
            )
        metadata = import_data.get("metadata") or {}
        if not metadata.get("name"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid inventory file. Missing metadata.",
            )

        inventory_id = persistence.create_inventory(
            {
                "name": f"{metadata['name']} (imported)",
                "description": metadata.get("description", "Imported inventory"),
                "conditions": [{"version": 2, "tree": import_data["conditionTree"]}],
                "template_category": None,
                "template_name": None,
                "scope": "global",
                "created_by": current_user.username,
            }
        )
        if not inventory_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create imported inventory",
            )
        inventory = persistence.get_inventory(inventory_id)
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Inventory created but could not be retrieved",
            )
        return InventoryResponse(**inventory)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to import inventory: ", exc)


@router.get(
    "/{inventory_id}",
    response_model=InventoryResponse,
    dependencies=[Depends(require_permission("sources.nautobot", "read"))],
)
async def get_inventory(
    inventory_id: int,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> InventoryResponse:
    try:
        inventory = persistence.get_inventory(inventory_id, username=current_user.username)
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inventory with ID {inventory_id} not found",
            )
        return InventoryResponse(**inventory)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to get inventory: ", exc)


@router.put(
    "/{inventory_id}",
    response_model=InventoryResponse,
    dependencies=[Depends(require_permission("sources.nautobot", "write"))],
)
async def update_inventory(
    inventory_id: int,
    request: UpdateInventoryRequest,
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> InventoryResponse:
    try:
        update_data = {}
        if request.name is not None:
            update_data["name"] = request.name
        if request.description is not None:
            update_data["description"] = request.description
        if request.conditions is not None:
            update_data["conditions"] = request.conditions
        if request.template_category is not None:
            update_data["template_category"] = request.template_category
        if request.template_name is not None:
            update_data["template_name"] = request.template_name
        if request.scope is not None:
            update_data["scope"] = request.scope
        if "group_path" in request.model_fields_set:
            update_data["group_path"] = request.group_path
        persistence.update_inventory(inventory_id, update_data, current_user.username)
        inventory = persistence.get_inventory(inventory_id)
        if not inventory:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Inventory with ID {inventory_id} not found after update",
            )
        return InventoryResponse(**inventory)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to update inventory: ", exc)


@router.delete(
    "/{inventory_id}",
    response_model=InventoryDeleteResponse,
    dependencies=[Depends(require_permission("sources.nautobot", "delete"))],
)
async def delete_inventory(
    inventory_id: int,
    hard_delete: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    persistence: InventoryService = Depends(get_inventory_service),
) -> InventoryDeleteResponse:
    try:
        persistence.delete_inventory(inventory_id, current_user.username, hard_delete)
        return InventoryDeleteResponse(
            success=True,
            message=f"Inventory {'deleted' if hard_delete else 'deactivated'} successfully",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to delete inventory: ", exc)
