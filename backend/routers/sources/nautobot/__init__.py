from routers.sources.nautobot.crud import router as nautobot_source_crud_router
from routers.sources.nautobot.ops import router as nautobot_source_ops_router

__all__ = ["nautobot_source_ops_router", "nautobot_source_crud_router"]
