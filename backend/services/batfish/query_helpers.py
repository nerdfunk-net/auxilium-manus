"""Shared, workflow-agnostic helpers for building and running Batfish queries.

Used by the batfish-routing-table/batfish-path-check/batfish-acl-check
workflow-step executors (via workflow_steps.common.batfish_context) AND the
ad-hoc BatfishPreviewService, so a Template Editor preview query behaves
*identically* to what the corresponding workflow step would produce -- not
just similarly. `query_routes`/`query_reachability`/`query_test_filters` are
the one place each question's pybatfish call is actually built and made;
callers are responsible only for resolving the connection/snapshot first
(each has a different way to do that -- run metadata vs. an explicit
network) and validating their own required fields *before* calling these
(via `require_field`), so a fail-fast check never triggers an unnecessary
Batfish round-trip.
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


def _or_none(value: Any) -> Any:
    """``None`` means "not set" to pybatfish's question constructors (which
    reject unexpected kwargs) -- blank strings must be normalized to it."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def require_field(value: Any, field_name: str) -> str:
    """Strip ``value`` and raise ``ValueError`` if it's blank.

    The one shared shape for every "this field is required" check across
    both callers -- previously each spelled its own
    ``str(x or "").strip(); if not x: raise ...`` inline, with inconsistent
    message wording between the workflow-step and preview-service copies.
    """
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{field_name} is required")
    return clean


async def query_routes(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    nodes: Any = None,
    network_prefix: Any = None,
    prefix_match_type: Any = None,
    protocols: Any = None,
    vrfs: Any = None,
    rib: Any = None,
) -> list[dict[str, Any]]:
    """Run the ``routes`` question. Shared by batfish-routing-table's
    executor and ``BatfishPreviewService.run_routes``.

    ``network_prefix`` maps to pybatfish's own ``network`` parameter on the
    ``routes()`` question (a route-prefix filter) -- kept a distinct name
    here for the same reason ``BatfishService.routes()`` takes the Batfish
    network as ``batfish_network``: to avoid colliding with it.
    """
    return await batfish.routes(
        connection,
        batfish_network=batfish_network,
        snapshot=snapshot,
        nodes=_or_none(nodes),
        network=_or_none(network_prefix),
        prefixMatchType=_or_none(prefix_match_type),
        protocols=_or_none(protocols),
        vrfs=_or_none(vrfs),
        rib=_or_none(rib),
    )


async def query_reachability(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    start_node: str,
    end_node: Any = None,
    dst_ips: Any = None,
    src_ips: Any = None,
    applications: Any = None,
    ip_protocols: Any = None,
    max_traces: Any = None,
    invert_search: bool = False,
    ignore_filters: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    """Run the ``reachability`` question. Shared by batfish-path-check's
    executor and ``BatfishPreviewService.run_reachability``.

    ``start_node`` is assumed already validated non-blank by the caller (via
    `require_field`) -- validating it here too would mean every caller pays
    for a Batfish snapshot-listing round-trip (in `resolve_latest_snapshot_name`)
    before finding out the request was incomplete. Returns ``(rows,
    reachable)`` -- an empty result set is a legitimate negative answer, not
    an error, for this question.
    """
    path_constraints: dict[str, Any] = {"startLocation": start_node}
    end_node_clean = str(end_node or "").strip()
    if end_node_clean:
        path_constraints["endLocation"] = end_node_clean

    headers = build_batfish_headers(
        dst_ips=dst_ips, src_ips=src_ips, applications=applications, ip_protocols=ip_protocols
    )

    rows = await batfish.reachability(
        connection,
        batfish_network=batfish_network,
        snapshot=snapshot,
        pathConstraints=path_constraints,
        headers=headers or None,
        maxTraces=max_traces,
        invertSearch=bool(invert_search),
        ignoreFilters=bool(ignore_filters),
    )
    return rows, len(rows) > 0


async def query_test_filters(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    node: str,
    filter_name: str,
    dst_ips: str,
    src_ips: Any = None,
    applications: Any = None,
    ip_protocols: Any = None,
    start_location: Any = None,
) -> tuple[list[dict[str, Any]], str]:
    """Run the ``testFilters`` question. Shared by batfish-acl-check's
    executor and ``BatfishPreviewService.run_test_filters``.

    ``node``/``filter_name``/``dst_ips`` are assumed already validated
    non-blank by the caller (via `require_field`), for the same fail-fast
    reason as `query_reachability`. Unlike reachability, an empty result set
    here means the node/filter_name didn't match anything in the snapshot --
    an execution problem, not a verdict -- so this raises ``RuntimeError``
    rather than returning it as a `deny`.
    """
    headers = build_batfish_headers(
        dst_ips=dst_ips, src_ips=src_ips, applications=applications, ip_protocols=ip_protocols
    )
    start_location_clean = str(start_location or "").strip() or None

    rows = await batfish.test_filters(
        connection,
        batfish_network=batfish_network,
        snapshot=snapshot,
        nodes=node,
        filters=filter_name,
        headers=headers,
        startLocation=start_location_clean,
    )
    if not rows:
        raise RuntimeError(
            "No result returned -- check that node/filter_name match the snapshot"
        )
    action = str(rows[0].get("Action", "")).strip().upper()
    return rows, action
