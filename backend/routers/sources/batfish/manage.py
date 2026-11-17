"""Manage Batfish networks and snapshots of a configured source.

Backs the "Manage" dialog on Settings -> Sources: remove a network, remove snapshots, and show the
devices (with IP addresses) of a snapshot.

Every route first confirms that the network exists (``assert_batfish_network_exists``): pybatfish's
``set_network`` silently *creates* a missing network, so an unverified name must never reach it
(see ``discovery.py``). Deletes are irreversible and need ``sources.batfish:write``; the device
table shows network-wide data and needs ``sources.batfish:query``.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, Response, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.rate_limit import rate_limited
from core.safe_http_errors import client_error_message, raise_internal_server_error
from dependencies import get_batfish_preview_service, get_batfish_source_config_service
from models.batfish import (
    MAX_PREVIEW_ROWS,
    BatfishDeleteSnapshotsRequest,
    BatfishDeleteSnapshotsResponse,
    BatfishSnapshotDevice,
    BatfishSnapshotDevicesResponse,
    ensure_safe_batfish_name,
)
from services.batfish.client import PREVIEW_ROW_LIMIT
from services.batfish.common.exceptions import BatfishAPIError, BatfishValidationError
from services.batfish.preview_service import BatfishPreviewService
from services.batfish.query_helpers import assert_batfish_network_exists, assert_snapshot_exists
from services.batfish.source_config_service import (
    BatfishSourceConfigService,
    BatfishSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/batfish",
    tags=["sources-batfish"],
    dependencies=[Depends(rate_limited("batfish-manage", attempts=30, window_seconds=60))],
)


@contextmanager
def _mapped_errors(action: str) -> Generator[None]:
    """Translate service errors into the HTTP errors the other Batfish routes use."""
    try:
        yield
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=client_error_message(exc)
        ) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger, f"{action}: ", exc, status_code=status.HTTP_502_BAD_GATEWAY
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, f"{action}: ", exc)


async def _cap_preview_rows() -> None:
    """Bound the rows a device table materialises (async: runs in the request's own task)."""
    PREVIEW_ROW_LIMIT.set(MAX_PREVIEW_ROWS)


@router.delete(
    "/{source_id}/networks/{network}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("sources.batfish", "write"))],
)
async def delete_batfish_network(
    source_id: str,
    network: str,
    user: User = Depends(get_current_user),
    config: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> Response:
    with _mapped_errors("Failed to delete Batfish network"):
        ensure_safe_batfish_name(network)
        connection = config.resolve_connection(source_id)
        batfish = service_factory.get_batfish_app_service()
        await assert_batfish_network_exists(batfish, connection, network)
        await batfish.delete_network(connection, network=network)
        logger.info("User %s deleted Batfish network %r on source %r", user.id, network, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{source_id}/networks/{network}/snapshots/delete",
    response_model=BatfishDeleteSnapshotsResponse,
    dependencies=[Depends(require_permission("sources.batfish", "write"))],
)
async def delete_batfish_snapshots(
    source_id: str,
    network: str,
    request: BatfishDeleteSnapshotsRequest,
    user: User = Depends(get_current_user),
    config: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> BatfishDeleteSnapshotsResponse:
    deleted: list[str] = []
    failed: list[str] = []
    with _mapped_errors("Failed to delete Batfish snapshots"):
        ensure_safe_batfish_name(network)
        connection = config.resolve_connection(source_id)
        batfish = service_factory.get_batfish_app_service()
        await assert_batfish_network_exists(batfish, connection, network)
        # One listing validates every name; an unknown name is reported as failed, not deleted.
        known = {
            str(entry.get("name"))
            for entry in await batfish.list_snapshots_with_metadata(
                connection, batfish_network=network
            )
        }
        for name in dict.fromkeys(request.snapshots):
            if name not in known:
                failed.append(name)
                continue
            try:
                await batfish.delete_snapshot(
                    connection, batfish_network=network, snapshot_name=name
                )
                deleted.append(name)
            except BatfishAPIError:
                logger.warning("Could not delete Batfish snapshot %r of %r", name, network)
                failed.append(name)
        logger.info(
            "User %s deleted %d Batfish snapshot(s) of network %r on source %r (%d failed)",
            user.id,
            len(deleted),
            network,
            source_id,
            len(failed),
        )
    return BatfishDeleteSnapshotsResponse(deleted=deleted, failed=failed)


@router.get(
    "/{source_id}/networks/{network}/snapshots/{snapshot}/devices",
    response_model=BatfishSnapshotDevicesResponse,
    dependencies=[
        Depends(require_permission("sources.batfish", "query")),
        Depends(_cap_preview_rows),
    ],
)
async def list_batfish_snapshot_devices(
    source_id: str,
    network: str,
    snapshot: str,
    _: User = Depends(get_current_user),
    config: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
    preview: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishSnapshotDevicesResponse:
    with _mapped_errors("Failed to list Batfish snapshot devices"):
        ensure_safe_batfish_name(network)
        ensure_safe_batfish_name(snapshot)
        connection = config.resolve_connection(source_id)
        batfish = service_factory.get_batfish_app_service()
        await assert_batfish_network_exists(batfish, connection, network)
        await assert_snapshot_exists(batfish, connection, network, snapshot)
        result = await preview.run_snapshot_devices(
            source_id, network, snapshot, None, with_ips=True
        )

    ips_by_node: dict[str, list[str]] = {}
    for row in result.ip_rows:
        node = str(row.get("Node", ""))
        ip = str(row.get("IP", ""))
        if node and ip and ip not in ips_by_node.setdefault(node, []):
            ips_by_node[node].append(ip)
    names = sorted(
        {str(r.get("Node", "")) for r in result.node_rows if r.get("Node")} | set(ips_by_node),
        key=str.casefold,
    )
    return BatfishSnapshotDevicesResponse(
        snapshot=result.snapshot,
        devices=[
            BatfishSnapshotDevice(device=name, ip_addresses=ips_by_node.get(name, []))
            for name in names
        ],
        ips_unavailable="ips" in result.unavailable,
        truncated=bool(result.truncated_sections),
    )
