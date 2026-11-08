"""Client data: where MAC and IP addresses were seen (doc/CLIENT_DATA.md).

Read-only. Needs ``client_data:read`` (not part of the seeded viewer role): the data shows where
a host is plugged in right now. The data is written by the ``collect-client-data`` workflow step.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.rate_limit import rate_limited
from models.client_data_api import ClientDataPage, ClientHistory, CollectionInfo
from services.client_data.client_data_service import (
    DEFAULT_HISTORY_ROWS,
    MAX_HISTORY_ROWS,
    MAX_PAGE_SIZE,
    ClientDataService,
)

router = APIRouter(
    prefix="/client-data",
    tags=["client-data"],
    dependencies=[Depends(get_current_user), Depends(require_permission("client_data", "read"))],
)

# Each query correlates the whole current data set; keep one user from hammering it.
_READ_BUDGET = rate_limited("client-data-read", attempts=120, window_seconds=60)

Filter = Annotated[str | None, Query(max_length=255)]
# The start of an address: digits, hex letters, dots and colons only (a CIDR is not a prefix).
IpPrefix = Annotated[str | None, Query(max_length=45, pattern=r"^[0-9A-Fa-f:.]*$")]


def get_client_data_service(db: Session = Depends(get_db)) -> ClientDataService:
    return ClientDataService(db)


@router.get("", response_model=ClientDataPage, dependencies=[Depends(_READ_BUDGET)])
def list_client_data(
    device_name: Filter = None,
    ip_address: Filter = None,
    mac_address: Filter = None,
    port: Filter = None,
    vlan: Filter = None,
    vrf: Filter = None,
    hostname: Filter = None,
    ip_prefix: IpPrefix = None,
    hide_uplinks: bool = False,
    exact: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=MAX_PAGE_SIZE),
    service: ClientDataService = Depends(get_client_data_service),
) -> ClientDataPage:
    """Current observations (newest collection of each device). Filters are case-insensitive
    substrings, or whole values with ``exact``; ``ip_prefix`` matches the start of the address;
    ``hide_uplinks`` leaves out uplink ports."""
    items, total = service.get_client_data(
        device_name=device_name,
        ip_address=ip_address,
        mac_address=mac_address,
        port=port,
        vlan=vlan,
        vrf=vrf,
        hostname=hostname,
        ip_prefix=ip_prefix,
        hide_uplinks=hide_uplinks,
        exact=exact,
        page=page,
        page_size=page_size,
    )
    return ClientDataPage.model_validate(
        {"items": items, "total": total, "page": page, "page_size": page_size}
    )


@router.get("/history", response_model=ClientHistory, dependencies=[Depends(_READ_BUDGET)])
def get_client_history(
    ip_address: Filter = None,
    mac_address: Filter = None,
    hostname: Filter = None,
    limit: int = Query(default=DEFAULT_HISTORY_ROWS, ge=1, le=MAX_HISTORY_ROWS),
    service: ClientDataService = Depends(get_client_data_service),
) -> ClientHistory:
    """Observations of one IP, MAC or hostname across the retained collections, newest first."""
    if sum(bool(value) for value in (ip_address, mac_address, hostname)) != 1:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Give exactly one of ip_address, mac_address or hostname"
        )
    return ClientHistory.model_validate(
        service.get_client_history(
            ip_address=ip_address, mac_address=mac_address, hostname=hostname, limit=limit
        )
    )


@router.get("/devices", response_model=list[CollectionInfo], dependencies=[Depends(_READ_BUDGET)])
def list_collected_devices(
    service: ClientDataService = Depends(get_client_data_service),
) -> list[CollectionInfo]:
    """Each device's newest collection with the outcome of its commands (coverage)."""
    return [CollectionInfo.model_validate(row) for row in service.get_collections()]
