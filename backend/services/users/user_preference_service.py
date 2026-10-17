from __future__ import annotations

from sqlalchemy.orm import Session

from models.user_preferences import DashboardLayoutResponse, DashboardLayoutUpdate
from repositories.user_preference_repository import UserPreferenceRepository


class UserPreferenceService:
    def __init__(self, db: Session) -> None:
        self._repo = UserPreferenceRepository(db)

    def get_dashboard_layout(self, user_id: int) -> DashboardLayoutResponse:
        preference = self._repo.get_by_user_id(user_id)
        return DashboardLayoutResponse(
            layout=preference.dashboard_layout if preference else None
        )

    def update_dashboard_layout(
        self, user_id: int, data: DashboardLayoutUpdate
    ) -> DashboardLayoutResponse:
        preference = self._repo.upsert_dashboard_layout(user_id, data.layout)
        return DashboardLayoutResponse(layout=preference.dashboard_layout)
