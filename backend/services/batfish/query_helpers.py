"""Shared, workflow-agnostic helpers for building and running Batfish queries.

Used by the batfish-routing-table/batfish-path-check/batfish-acl-check/
batfish-start-run workflow-step executors (via
workflow_steps.common.batfish_context) AND the ad-hoc BatfishPreviewService,
so a Template Editor preview query behaves *identically* to what the
corresponding workflow step would produce -- not just similarly.
`query_routes`/`query_reachability`/`query_test_filters`/`query_node_properties`
are the one place each question's pybatfish call is actually built and made;
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

# The generic ad-hoc question surface (Template Editor "Custom Question..."
# + POST /sources/batfish/{id}/query/generic) accepts a question NAME from
# request input, which BatfishService._answer/generic_question dispatch onto
# `session.q.<name>` with no validation of their own -- so every name here
# MUST be checked before BatfishService.generic_question is ever called (see
# query_generic below), never trusted directly. Each entry was empirically
# confirmed to answer against a live coordinator (a synthetic two-router
# snapshot with BGP/OSPF/VRF/ACL configured) rather than assumed from
# Batfish's public docs -- see doc/BATFISH_INTEGRATION.md "Template Editor
# integration" for the verification method and why three documented-sounding
# names (vrfProperties/aclReachability/subnetMultipleAccess) were dropped:
# they don't exist under those names in the installed pybatfish/coordinator
# version. Excluded on purpose: anything needing a second/reference snapshot
# (differentialReachability, compareFilters, ...) -- out of scope for this
# single-snapshot ad-hoc surface -- and every question already covered by a
# typed step/endpoint (routes/reachability/testFilters/nodeProperties/
# interfaceProperties).
GENERIC_QUESTION_ALLOWLIST: frozenset[str] = frozenset(
    {
        "bgpPeerConfiguration",
        "bgpProcessConfiguration",
        "bgpEdges",
        "bgpSessionCompatibility",
        "bgpSessionStatus",
        "ospfProcessConfiguration",
        "ospfInterfaceConfiguration",
        "ospfEdges",
        "namedStructures",
        "ipOwners",
        "edges",
        "undefinedReferences",
        "unusedStructures",
        "filterLineReachability",
        "switchedVlanProperties",
    }
)


async def assert_batfish_network_exists(
    batfish: BatfishService, connection: BatfishConnection, network: str
) -> None:
    """Raise ``ValueError`` if ``network`` doesn't already exist on the coordinator.

    Every caller that resolves a ``(connection, network)`` pair from
    caller-supplied config -- direct network targeting on a query/fact step
    (``resolve_batfish_snapshot_ref``), or an ad-hoc preview query
    (``BatfishPreviewService._resolve``) -- MUST call this before touching
    anything that reaches ``BatfishService._get_session(connection,
    network)``. pybatfish's own ``Session.set_network()`` silently *creates*
    the network if it doesn't already exist (confirmed by reading the
    installed pybatfish source: it 404s a lookup, then unconditionally calls
    ``restv2helper.init_network``) -- without this guard, a typo'd or
    not-yet-created network name doesn't fail loudly, it leaves a permanent
    junk network on the coordinator instead. This is exactly the bug that
    hit the networks/snapshots discovery picker before it gained the same
    guard -- see doc/BATFISH_INTEGRATION.md "Open items".
    """
    existing_networks = await batfish.list_networks(connection)
    if network not in existing_networks:
        raise ValueError(
            f"Batfish network {network!r} does not exist on this source -- check for "
            "a typo, or initialize it first (e.g. an upstream Init Batfish Snapshot "
            "step for a workflow-scoped network)."
        )


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


async def query_node_properties(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    nodes: Any = None,
    properties: Any = None,
) -> list[dict[str, Any]]:
    """Run the ``nodeProperties`` question. Shared by batfish-start-run's
    executor (as "Get from Batfish") and batfish-node-properties.

    Always includes a ``Node`` column (same convention
    ``routes``/``reachability``/``testFilters`` use) -- confirmed against
    ``pybatfish.client._facts.get_facts()``'s own use of this question, which
    is the same one Batfish's built-in fact extraction relies on. ``nodes``
    defaults to every node in the snapshot when blank (pybatfish's own
    default is ``"/.*/"``).

    ``properties`` is a NodePropertySpec (comma-separated property names,
    e.g. ``"TACACS_Servers, TACACS_Source_Interface"``) restricting which
    columns come back, on top of ``Node``. Left blank, Batfish returns its
    own default column set. batfish-start-run always leaves this unset --
    it only needs node identity for dedup, not fact contents -- so this
    parameter defaulting to ``None`` (omitted, not an empty string) preserves
    that call's existing behavior unchanged.
    """
    return await batfish.node_properties(
        connection,
        batfish_network=batfish_network,
        snapshot=snapshot,
        nodes=_or_none(nodes),
        properties=_or_none(properties),
    )


async def query_interface_properties(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    nodes: Any = None,
    interfaces: Any = None,
    properties: Any = None,
) -> list[dict[str, Any]]:
    """Run the ``interfaceProperties`` question. Shared by
    batfish-interface-properties.

    A different, interface-scoped question from ``nodeProperties`` -- one row
    per (node, interface) pair, not one row per node. ``nodes`` (a
    NodeSpecifier) restricts by node -- confirmed accepted by this question
    via ``pybatfish.client._facts.get_facts()``, which passes the same
    ``nodes`` kwarg to every property question it calls, this one included.
    ``interfaces`` (an InterfacesSpecifier, e.g. ``"GigabitEthernet0/1"`` or a
    regex) further restricts to matching interfaces on those nodes --
    documented Batfish convention for this question family, NOT independently
    exercised against a live coordinator in this codebase (unlike ``nodes``);
    an incorrect param name would surface immediately as a rejected-kwarg
    error from pybatfish, not silently. ``properties`` restricts which
    columns come back, same convention as ``query_node_properties``.
    """
    return await batfish.interface_properties(
        connection,
        batfish_network=batfish_network,
        snapshot=snapshot,
        nodes=_or_none(nodes),
        interfaces=_or_none(interfaces),
        properties=_or_none(properties),
    )


async def query_ospf_process_configuration(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    nodes: Any = None,
) -> list[dict[str, Any]]:
    """Run the ``ospfProcessConfiguration`` question. Shared by
    batfish-ospf-facts. One row per (Node, VRF, Process_ID) -- confirmed live
    that a node running OSPF in more than one VRF gets more than one row, see
    doc/BATFISH_INTEGRATION.md "Batfish OSPF Facts".
    """
    return await batfish.ospf_process_configuration(
        connection, batfish_network=batfish_network, snapshot=snapshot, nodes=_or_none(nodes)
    )


async def query_ospf_area_configuration(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    nodes: Any = None,
) -> list[dict[str, Any]]:
    """Run the ``ospfAreaConfiguration`` question. Shared by
    batfish-ospf-facts. One row per (Node, VRF, Process_ID, Area) -- an ABR
    spanning multiple areas gets one row per area, confirmed live against a
    synthetic multi-area snapshot, see doc/BATFISH_INTEGRATION.md "Batfish
    OSPF Facts".
    """
    return await batfish.ospf_area_configuration(
        connection, batfish_network=batfish_network, snapshot=snapshot, nodes=_or_none(nodes)
    )


async def query_ospf_interface_configuration(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    nodes: Any = None,
) -> list[dict[str, Any]]:
    """Run the ``ospfInterfaceConfiguration`` question. Shared by
    batfish-ospf-facts. One row per (node, interface), same nested
    ``Interface`` identity shape as ``interfaceProperties``.
    """
    return await batfish.ospf_interface_configuration(
        connection, batfish_network=batfish_network, snapshot=snapshot, nodes=_or_none(nodes)
    )


async def query_ospf_edges(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    nodes: Any = None,
) -> list[dict[str, Any]]:
    """Run the ``ospfEdges`` question. Shared by batfish-ospf-facts. One row
    per OSPF adjacency, with a local ``Interface`` and a ``Remote_Interface``
    (same nested shape). ``nodes`` filters by the local node -- confirmed live
    against a synthetic snapshot; a separate ``remoteNodes`` param also exists
    on this question but is not exposed here (see
    doc/BATFISH_INTEGRATION.md "Batfish OSPF Facts").
    """
    return await batfish.ospf_edges(
        connection, batfish_network=batfish_network, snapshot=snapshot, nodes=_or_none(nodes)
    )


async def query_generic(
    batfish: BatfishService,
    connection: BatfishConnection,
    *,
    batfish_network: str,
    snapshot: str,
    question_name: str,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run any question in ``GENERIC_QUESTION_ALLOWLIST``, with arbitrary
    caller-supplied ``params`` forwarded as kwargs. Shared by the ad-hoc
    ``/sources/batfish/{id}/query/generic`` endpoint and
    ``BatfishPreviewService.run_generic`` -- the ad-hoc-only counterpart to
    the typed ``query_routes``/``query_reachability``/``query_test_filters``/
    ``query_node_properties``/``query_interface_properties`` above.

    Raises ``ValueError`` for a non-allow-listed ``question_name`` -- this is
    the actual security boundary; ``BatfishService.generic_question``/
    ``_answer`` perform no allow-listing of their own (see that method's
    docstring). Unlike the typed ``query_*`` functions, per-param validation
    is left to pybatfish itself: an unsupported param name for the chosen
    question surfaces as a rejected-kwarg error, not silently -- there is no
    static schema for each allow-listed question's accepted params in this
    codebase to validate against ahead of time.
    """
    if question_name not in GENERIC_QUESTION_ALLOWLIST:
        raise ValueError(
            f"Batfish question {question_name!r} is not allow-listed for ad-hoc queries -- "
            f"allowed: {', '.join(sorted(GENERIC_QUESTION_ALLOWLIST))}"
        )
    clean_params = {k: _or_none(v) for k, v in (params or {}).items()}
    clean_params = {k: v for k, v in clean_params.items() if v is not None}
    return await batfish.generic_question(
        connection,
        batfish_network=batfish_network,
        snapshot=snapshot,
        question_name=question_name,
        **clean_params,
    )
