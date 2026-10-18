from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.rate_limit import rate_limited
from models.hatchet import (
    HatchetConfigResponse,
    HatchetRunDiagnostics,
    HatchetStatusResponse,
    HatchetWorkersResponse,
)
from services.execution.run_service import RunService
from services.hatchet.hatchet_diagnostics_service import HatchetDiagnosticsService
from services.hatchet.hatchet_settings_service import HatchetSettingsService

router = APIRouter(
    prefix="/hatchet",
    tags=["hatchet"],
    dependencies=[Depends(get_current_user)],
)


def _service() -> HatchetSettingsService:
    return HatchetSettingsService()


@router.get(
    "/settings",
    response_model=HatchetConfigResponse,
    dependencies=[Depends(require_permission("hatchet_settings", "read"))],
)
def get_hatchet_settings(
    service: HatchetSettingsService = Depends(_service),
) -> HatchetConfigResponse:
    return service.get_config()


@router.post(
    "/test",
    response_model=HatchetStatusResponse,
    dependencies=[Depends(require_permission("hatchet_settings", "read"))],
)
async def test_hatchet_connection(
    service: HatchetSettingsService = Depends(_service),
) -> HatchetStatusResponse:
    return await service.check_connection()


@router.get(
    "/workers",
    response_model=HatchetWorkersResponse,
    dependencies=[
        Depends(require_permission("hatchet_settings", "read")),
        Depends(rate_limited("hatchet-diagnostics", attempts=60, window_seconds=60)),
    ],
)
async def get_hatchet_workers() -> HatchetWorkersResponse:
    return await HatchetDiagnosticsService().get_workers()


@router.get(
    "/runs/{run_id}",
    response_model=HatchetRunDiagnostics,
    dependencies=[
        Depends(require_permission("hatchet_settings", "read")),
        Depends(rate_limited("hatchet-diagnostics", attempts=60, window_seconds=60)),
    ],
)
async def get_hatchet_run_diagnostics(
    run_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HatchetRunDiagnostics:
    """The engine's view of one run. The caller must also be allowed to see the run's workflow."""
    run = RunService(db).get_run(run_id=run_id, user_id=current_user.id)
    # Hand the pooled connection back before the (possibly slow) engine calls.
    db.commit()
    return await HatchetDiagnosticsService().get_run_diagnostics(run)
