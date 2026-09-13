"""Shared, workflow-agnostic helpers for building Batfish query parameters.

Used by the batfish-routing-table/batfish-path-check/batfish-acl-check
workflow-step executors (via workflow_steps.common.batfish_context) AND the
ad-hoc BatfishPreviewService, so a Template Editor preview query behaves
identically to what the corresponding workflow step would produce.
"""

from __future__ import annotations

from typing import Any

from services.batfish.client import BatfishService
from services.batfish.credentials import BatfishConnection


async def resolve_latest_snapshot_name(
    batfish: BatfishService, connection: BatfishConnection, network: str
) -> str:
    """Pick the most recently created snapshot in ``network``.

    Snapshot names are not chronologically sortable (see
    doc/BATFISH_INTEGRATION.md "Snapshot lifecycle"), so this sorts by each
    snapshot's ``metadata.creationTimestamp`` instead -- a fixed-width,
    always-UTC, "Z"-suffixed ISO 8601 string, safe to sort lexically.
    """
    entries = await batfish.list_snapshots_with_metadata(connection, batfish_network=network)
    if not entries:
        raise ValueError(
            f"No Batfish snapshots found in network {network!r} -- run Init Batfish "
            "Snapshot against this network first, or set 'snapshot' explicitly."
        )
    entries_sorted = sorted(
        entries, key=lambda e: e.get("metadata", {}).get("creationTimestamp", "")
    )
    return str(entries_sorted[-1]["name"])


def build_batfish_headers(
    *,
    dst_ips: str | None = None,
    src_ips: str | None = None,
    applications: Any = None,
    ip_protocols: str | None = None,
) -> dict[str, Any]:
    """Build a Batfish ``headers`` constraint dict, dropping unset fields.

    Shared by batfish-path-check (``dst_ips`` optional) and batfish-acl-check
    (``dst_ips`` required, validated by the caller before this is invoked).
    """
    headers: dict[str, Any] = {}
    dst_ips_clean = str(dst_ips or "").strip()
    if dst_ips_clean:
        headers["dstIps"] = dst_ips_clean
    src_ips_clean = str(src_ips or "").strip()
    if src_ips_clean:
        headers["srcIps"] = src_ips_clean
    if applications:
        headers["applications"] = applications
    ip_protocols_clean = str(ip_protocols or "").strip()
    if ip_protocols_clean:
        headers["ipProtocols"] = ip_protocols_clean
    return headers
