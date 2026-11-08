"""Service for the client data tables (IP / MAC / hostname observations per device)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from core.config import settings
from models.client_data import (
    ClientCollectionStatus,
    ClientHostnameRow,
    ClientIpRow,
    ClientMacRow,
    check_row_cap,
)
from repositories.client_data_query_repository import (
    DEFAULT_HISTORY_ROWS,
    MAX_HISTORY_ROWS,
    MAX_PAGE_SIZE,
    ClientDataQueryRepository,
)
from repositories.client_data_repository import ClientDataRepository

logger = logging.getLogger(__name__)

# Re-exported for the router (a router may not import repositories).
__all__ = ["DEFAULT_HISTORY_ROWS", "MAX_HISTORY_ROWS", "MAX_PAGE_SIZE", "ClientDataService"]

_SESSION_ID_MAX = 36  # a run uuid
_DEVICE_NAME_MAX = 255


class ClientDataService:
    def __init__(self, db: Session, *, uplink_threshold: int | None = None) -> None:
        self.repository = ClientDataRepository(db)
        self.queries = ClientDataQueryRepository(
            db,
            uplink_threshold=(
                settings.client_data_uplink_mac_threshold
                if uplink_threshold is None
                else uplink_threshold
            ),
        )

    def get_client_data(self, **filters: Any) -> tuple[list[dict[str, Any]], int]:
        """Current observations, filtered and paged (see ``ClientDataQueryRepository``)."""
        return self.queries.get_client_data(**filters)

    def get_client_history(self, **filters: Any) -> dict[str, list[dict[str, Any]]]:
        return self.queries.get_client_history(**filters)

    def get_collections(self) -> list[dict[str, Any]]:
        return self.queries.get_collections()

    def store_device_collection(
        self,
        *,
        session_id: str,
        device_name: str,
        device_ip: str | None,
        ip_rows: Sequence[ClientIpRow],
        mac_rows: Sequence[ClientMacRow],
        hostname_rows: Sequence[ClientHostnameRow],
        status: ClientCollectionStatus,
        keep_sessions: int,
        collected_at: datetime | None = None,
        max_rows: int | None = None,
        target_host: str | None = None,
    ) -> None:
        """Replace one device's collection for *session_id* and prune its older ones.

        A table above the row cap (``max_rows``, default ``CLIENT_DATA_MAX_ROWS_PER_TABLE``)
        raises ``TooManyRowsError`` before anything is written.
        """
        if not session_id or len(session_id) > _SESSION_ID_MAX:
            raise ValueError(f"session_id must be 1-{_SESSION_ID_MAX} characters")
        if not device_name.strip() or len(device_name) > _DEVICE_NAME_MAX:
            raise ValueError(f"device_name must be 1-{_DEVICE_NAME_MAX} characters")
        check_row_cap(
            len(ip_rows),
            len(mac_rows),
            settings.client_data_max_rows_per_table if max_rows is None else max_rows,
        )
        self.repository.replace_device_collection(
            session_id=session_id,
            device_name=device_name,
            device_ip=device_ip,
            collected_at=collected_at or datetime.now(UTC),
            ip_rows=ip_rows,
            mac_rows=mac_rows,
            hostname_rows=hostname_rows,
            status=status,
            keep_sessions=keep_sessions,
            target_host=target_host,
        )

    def purge_older_than_days(self, days: int, *, batch_size: int = 1000) -> int:
        """Retention sweep; ``days < 1`` keeps everything. Each device's newest collection stays."""
        if days < 1:
            return 0
        deleted = self.repository.purge_older_than(
            datetime.now(UTC) - timedelta(days=days), batch_size=batch_size
        )
        logger.info("Purged %s client data row(s) older than %s day(s)", deleted, days)
        return deleted
