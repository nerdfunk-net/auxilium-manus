"""Batfish coordinator client.

App-scoped async wrapper around pybatfish's synchronous ``Session``. Sessions
are cached per ``(host, port, network)`` -- never per ``(host, port)`` alone
-- because ``Session.set_network()`` mutates shared state with no per-call
override, so sharing a session across concurrent callers targeting different
networks would race on which network is "current". A cache entry's
``.network`` is fixed exactly once, at creation, and never mutated again --
see doc/BATFISH_INTEGRATION.md "Session caching and concurrency safety" for
the full reasoning. ``snapshot`` is never relied on as session state; every
question call passes ``answer(snapshot=...)`` explicitly.

Every ``pybatfish`` call is synchronous/blocking (``requests``-based, no
asyncio support) -- including ``Session.__init__`` itself, which performs a
blocking HTTP call to load question templates -- so every call here runs via
``asyncio.to_thread(...)``, the same pattern used elsewhere in this codebase
for wrapping blocking libraries (``services/artifacts/filesystem_artifact_service.py``,
``services/artifacts/sinks/git_sink.py``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast

from pybatfish.client.session import Session
from pybatfish.exception import BatfishException

from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.credentials import BatfishConnection

logger = logging.getLogger(__name__)


class BatfishService:
    def __init__(self) -> None:
        self._sessions: dict[tuple[str, int, str], Session] = {}
        self._lock = asyncio.Lock()

    async def startup(self) -> None:
        logger.info("BatfishService started")

    async def shutdown(self) -> None:
        self._sessions.clear()
        logger.info("BatfishService shut down")

    async def list_networks(self, connection: BatfishConnection) -> list[str]:
        """List every network on the coordinator. Not cached -- like
        check_health, a throwaway Session's list_networks() doesn't depend on
        .network being set to anything in particular. Kept as its own method
        (not delegated to by check_health, or vice versa) so each keeps its
        own error-message wording for its own purpose -- connectivity check
        vs. a discovery listing a caller will show to a user.
        """

        def _list() -> list[str]:
            session = Session(host=connection.host, port=connection.port)
            return session.list_networks()

        try:
            return await asyncio.to_thread(_list)
        except BatfishException as exc:
            raise BatfishAPIError(f"Failed to list Batfish networks: {exc}") from exc
        except Exception as exc:
            logger.error("Failed to list Batfish networks: %s", exc)
            raise BatfishAPIError("Failed to list Batfish networks") from exc

    async def check_health(self, connection: BatfishConnection) -> list[str]:
        """Liveness/functional check for test-connection. Not cached -- a
        throwaway Session's list_networks() doesn't depend on .network being
        set to anything in particular.
        """

        def _check() -> list[str]:
            session = Session(host=connection.host, port=connection.port)
            return session.list_networks()

        try:
            return await asyncio.to_thread(_check)
        except BatfishException as exc:
            raise BatfishAPIError(f"Batfish coordinator rejected the request: {exc}") from exc
        except Exception as exc:
            logger.error("Batfish health check failed: %s", exc)
            raise BatfishAPIError("Batfish coordinator is not reachable") from exc

    async def init_snapshot(
        self,
        connection: BatfishConnection,
        *,
        batfish_network: str,
        snapshot_name: str,
        snapshot_dir: str,
        overwrite: bool = True,
    ) -> str:
        session = await self._get_session(connection, batfish_network)

        def _init() -> str:
            return session.init_snapshot(snapshot_dir, name=snapshot_name, overwrite=overwrite)

        try:
            return await asyncio.to_thread(_init)
        except BatfishException as exc:
            raise BatfishAPIError(f"Batfish snapshot init failed: {exc}") from exc
        except Exception as exc:
            logger.error("Batfish snapshot init failed: %s", exc)
            raise BatfishAPIError("Batfish snapshot init failed") from exc

    async def list_snapshots(
        self, connection: BatfishConnection, *, batfish_network: str
    ) -> list[str]:
        session = await self._get_session(connection, batfish_network)
        try:
            # verbose=False (the default) always returns list[str]; the stub's
            # broader union type only applies when verbose=True.
            names = await asyncio.to_thread(session.list_snapshots, verbose=False)
            return cast(list[str], names)
        except BatfishException as exc:
            raise BatfishAPIError(f"Failed to list Batfish snapshots: {exc}") from exc
        except Exception as exc:
            logger.error("Failed to list Batfish snapshots: %s", exc)
            raise BatfishAPIError("Failed to list Batfish snapshots") from exc

    async def list_snapshots_with_metadata(
        self, connection: BatfishConnection, *, batfish_network: str
    ) -> list[dict[str, Any]]:
        """Like list_snapshots, but with each entry's ``metadata.creationTimestamp``.

        Snapshot names are caller-chosen (e.g. ``run-<uuid>``) and not
        chronologically sortable by themselves -- retention sweeps must sort
        by this timestamp, not by name. Confirmed shape against a live
        coordinator: ``[{"name": ..., "metadata": {"creationTimestamp":
        "<ISO 8601 UTC, 'Z'-suffixed>", ...}}, ...]`` -- lexically sortable
        since the format is fixed-width and always UTC.
        """
        session = await self._get_session(connection, batfish_network)
        try:
            entries = await asyncio.to_thread(session.list_snapshots, verbose=True)
            return cast(list[dict[str, Any]], entries)
        except BatfishException as exc:
            raise BatfishAPIError(f"Failed to list Batfish snapshots: {exc}") from exc
        except Exception as exc:
            logger.error("Failed to list Batfish snapshots: %s", exc)
            raise BatfishAPIError("Failed to list Batfish snapshots") from exc

    async def delete_snapshot(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot_name: str
    ) -> None:
        session = await self._get_session(connection, batfish_network)
        try:
            await asyncio.to_thread(session.delete_snapshot, snapshot_name)
        except BatfishException as exc:
            raise BatfishAPIError(f"Failed to delete Batfish snapshot: {exc}") from exc
        except Exception as exc:
            logger.error("Failed to delete Batfish snapshot: %s", exc)
            raise BatfishAPIError("Failed to delete Batfish snapshot") from exc

    async def routes(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        # NOTE: keyword-argument-named batfish_network, not network -- pybatfish's own
        # routes() question has its own "network" parameter (a route-prefix filter,
        # e.g. "192.168.1.0/24"), which callers pass through **params. Naming this
        # parameter "network" would collide with that on every routes() call.
        return await self._answer(connection, batfish_network, snapshot, "routes", params)

    async def reachability(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        return await self._answer(connection, batfish_network, snapshot, "reachability", params)

    async def test_filters(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        return await self._answer(connection, batfish_network, snapshot, "testFilters", params)

    async def node_properties(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        return await self._answer(connection, batfish_network, snapshot, "nodeProperties", params)

    async def interface_properties(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        # NOTE: unlike every other question wrapped here, interfaceProperties'
        # rows have no plain "Node" string column -- node identity lives
        # nested at row["Interface"]["hostname"] once the pandas Interface
        # object round-trips through frame.to_json() (empirically confirmed;
        # see doc/BATFISH_INTEGRATION.md "Batfish Interface Properties").
        return await self._answer(
            connection, batfish_network, snapshot, "interfaceProperties", params
        )

    async def ospf_process_configuration(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        # Same identity shape as nodeProperties (plain "Node" string column) --
        # confirmed against a live coordinator, see doc/BATFISH_INTEGRATION.md
        # "Batfish OSPF Facts". A node can have more than one row (one per
        # VRF/Process_ID) -- multi-VRF OSPF is a legitimate, confirmed case.
        return await self._answer(
            connection, batfish_network, snapshot, "ospfProcessConfiguration", params
        )

    async def ospf_area_configuration(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        # Same identity shape as nodeProperties (plain "Node" string column) --
        # confirmed against a live coordinator. One row per (Node, VRF,
        # Process_ID, Area) -- an ABR spanning multiple areas gets one row per
        # area it participates in, see doc/BATFISH_INTEGRATION.md "Batfish
        # OSPF Facts".
        return await self._answer(
            connection, batfish_network, snapshot, "ospfAreaConfiguration", params
        )

    async def ospf_interface_configuration(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        # Same nested Interface identity shape as interfaceProperties -- one
        # row per (node, interface).
        return await self._answer(
            connection, batfish_network, snapshot, "ospfInterfaceConfiguration", params
        )

    async def ospf_edges(
        self, connection: BatfishConnection, *, batfish_network: str, snapshot: str, **params: Any
    ) -> list[dict[str, Any]]:
        # One row per OSPF adjacency: a local "Interface" (same nested shape
        # as interfaceProperties) plus a "Remote_Interface" of the same
        # shape. "nodes" filters by the LOCAL node; a separate "remoteNodes"
        # param filters by the remote node -- both confirmed against a live
        # coordinator (see doc/BATFISH_INTEGRATION.md "Batfish OSPF Facts"),
        # but only "nodes" is exposed by the workflow step, for consistency
        # with the other three OSPF questions.
        return await self._answer(connection, batfish_network, snapshot, "ospfEdges", params)

    async def generic_question(
        self,
        connection: BatfishConnection,
        *,
        batfish_network: str,
        snapshot: str,
        question_name: str,
        **params: Any,
    ) -> list[dict[str, Any]]:
        # NOTE: this forwards question_name straight to _answer's own
        # getattr(session.q, question_name) dispatch -- _answer performs NO
        # allow-listing of its own. Every caller of this method MUST have
        # already checked question_name against a hardcoded allow-list (see
        # services/batfish/query_helpers.py::GENERIC_QUESTION_ALLOWLIST)
        # before reaching here; this method exists to let an allow-listed
        # caller reach an arbitrary Batfish question, not to expose that
        # dispatch to raw request input on its own.
        return await self._answer(connection, batfish_network, snapshot, question_name, params)

    async def validate_facts(
        self,
        connection: BatfishConnection,
        *,
        batfish_network: str,
        expected_facts_dir: str,
        snapshot: str | None = None,
    ) -> dict[str, Any]:
        # NOTE: expected_facts_dir is a DIRECTORY path -- pybatfish's own
        # validate_facts() reads every file in it and merges their "nodes"
        # maps (see pybatfish.client._facts.load_facts). It always fetches
        # actual facts for every node in the snapshot and only reports nodes
        # that also appear in the expected-facts dict.
        session = await self._get_session(connection, batfish_network)

        def _validate() -> dict[str, Any]:
            return session.validate_facts(expected_facts_dir, snapshot=snapshot)

        try:
            return await asyncio.to_thread(_validate)
        except BatfishException as exc:
            raise BatfishAPIError(f"Batfish fact validation failed: {exc}") from exc
        except Exception as exc:
            logger.error("Batfish fact validation failed: %s", exc)
            raise BatfishAPIError("Batfish fact validation failed") from exc

    async def extract_facts(
        self,
        connection: BatfishConnection,
        *,
        batfish_network: str,
        nodes: str = "/.*/",
        snapshot: str | None = None,
    ) -> dict[str, Any]:
        session = await self._get_session(connection, batfish_network)

        def _extract() -> dict[str, Any]:
            return session.extract_facts(nodes=nodes, snapshot=snapshot)

        try:
            return await asyncio.to_thread(_extract)
        except BatfishException as exc:
            raise BatfishAPIError(f"Batfish fact extraction failed: {exc}") from exc
        except Exception as exc:
            logger.error("Batfish fact extraction failed: %s", exc)
            raise BatfishAPIError("Batfish fact extraction failed") from exc

    async def _answer(
        self,
        connection: BatfishConnection,
        network: str,
        snapshot: str,
        question_name: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        session = await self._get_session(connection, network)
        # None means "not set" -- pybatfish question constructors reject
        # unexpected kwargs, so omit rather than pass None through.
        clean_params = {k: v for k, v in params.items() if v is not None}

        def _run() -> list[dict[str, Any]]:
            question = getattr(session.q, question_name)
            frame = question(**clean_params).answer(snapshot=snapshot).frame()
            # numpy scalar types in DataFrame cells (e.g. numpy.int64) can
            # fail plain json.dumps; pandas' own to_json round-trip is safe.
            return json.loads(frame.to_json(orient="records"))

        try:
            return await asyncio.to_thread(_run)
        except BatfishException as exc:
            raise BatfishAPIError(f"Batfish question {question_name!r} failed: {exc}") from exc
        except Exception as exc:
            logger.error("Batfish question %r failed: %s", question_name, exc)
            raise BatfishAPIError(f"Batfish question {question_name!r} failed") from exc

    async def _get_session(self, connection: BatfishConnection, network: str) -> Session:
        key = (connection.host, connection.port, network)
        async with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = await asyncio.to_thread(
                    Session, host=connection.host, port=connection.port
                )
                await asyncio.to_thread(session.set_network, network)
                self._sessions[key] = session
            return session
