"""Networks/snapshots discovery for a configured Batfish source.

Lets the workflow-step config panels (BatfishDirectTargetFields) and the
Template Editor's Options-modal Batfish tab populate "network"/"snapshot" as
fetched dropdowns instead of free text -- BatfishService already exposed
everything needed for this (list_networks, list_snapshots_with_metadata);
see doc/BATFISH_INTEGRATION.md "Open items / verify during hardening".

**Critical constraint, discovered the hard way**: pybatfish's own
``Session.set_network(name)`` silently *creates* the network if it doesn't
already exist (confirmed by reading the installed pybatfish source --
``restv2helper.get_network`` 404s, then it calls
``restv2helper.init_network``). ``BatfishService._get_session()`` calls
``set_network()`` on every new ``(host, port, network)`` cache entry, and
``list_snapshots_with_metadata`` (used by ``list_batfish_snapshots`` below)
goes through that same cache. So calling it with an arbitrary,
not-yet-verified network name -- e.g. a value typed character-by-character
into a picker's fallback text field -- silently creates a real, empty
network on the coordinator per call. ``list_batfish_snapshots`` below MUST
confirm the network already exists (via ``list_networks``) before ever
touching ``list_snapshots_with_metadata``/``_get_session``/``set_network``.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_batfish_source_config_service
from models.batfish import BatfishNetworksResponse, BatfishSnapshotInfo, BatfishSnapshotsResponse
from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.source_config_service import (
    BatfishSourceConfigService,
    BatfishSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/batfish",
    tags=["sources-batfish"],
    dependencies=[Depends(require_permission("sources.batfish", "read"))],
)


@router.get("/{source_id}/networks", response_model=BatfishNetworksResponse)
async def list_batfish_networks(
    source_id: str,
    _: User = Depends(get_current_user),
    config: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> BatfishNetworksResponse:
    try:
        connection = config.resolve_connection(source_id)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    batfish = service_factory.get_batfish_app_service()
    try:
        networks = await batfish.list_networks(connection)
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Failed to list Batfish networks: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list Batfish networks: ", exc)

    return BatfishNetworksResponse(networks=sorted(networks))


@router.get(
    "/{source_id}/networks/{network}/snapshots",
    response_model=BatfishSnapshotsResponse,
)
async def list_batfish_snapshots(
    source_id: str,
    network: str,
    _: User = Depends(get_current_user),
    config: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> BatfishSnapshotsResponse:
    try:
        connection = config.resolve_connection(source_id)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    batfish = service_factory.get_batfish_app_service()
    try:
        existing_networks = await batfish.list_networks(connection)
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Failed to list Batfish networks: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list Batfish networks: ", exc)

    if network not in existing_networks:
        # Never touch list_snapshots_with_metadata for a network that isn't
        # confirmed to exist yet -- see the module docstring's
        # set_network()-creates-if-absent warning. An unknown network simply
        # has no snapshots to offer a picker, not an error.
        return BatfishSnapshotsResponse(snapshots=[])

    try:
        entries = await batfish.list_snapshots_with_metadata(connection, batfish_network=network)
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Failed to list Batfish snapshots: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to list Batfish snapshots: ", exc)

    snapshots = [
        BatfishSnapshotInfo(
            name=str(entry["name"]),
            created_at=str(entry.get("metadata", {}).get("creationTimestamp") or "") or None,
        )
        for entry in entries
        if entry.get("name")
    ]
    # Most-recent-first, same sort key resolve_latest_snapshot_name uses --
    # entries with no timestamp sort last, not first.
    snapshots.sort(key=lambda snap: snap.created_at or "", reverse=True)

    return BatfishSnapshotsResponse(snapshots=snapshots)
