"""RBAC administration routers: permission catalog, roles, and user role/permission access."""

from fastapi import APIRouter

from routers.rbac.permissions import router as permissions_router
from routers.rbac.roles import router as roles_router
from routers.rbac.user_access import router as user_access_router

router = APIRouter()
router.include_router(permissions_router)
router.include_router(roles_router)
router.include_router(user_access_router)

__all__ = ["router"]
