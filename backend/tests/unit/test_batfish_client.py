"""Tests for BatfishService: session caching, concurrency safety, and error mapping.

pybatfish.client.session.Session is mocked throughout -- these tests never
talk to a real coordinator (see docker/batfish/ for that, exercised manually
while writing doc/BATFISH_INTEGRATION.md).
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from pybatfish.exception import BatfishException

from services.batfish.client import BatfishService
from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.credentials import BatfishConnection


def _connection(**overrides) -> BatfishConnection:
    base = {"host": "batfish", "port": 9996}
    base.update(overrides)
    return BatfishConnection(**base)


class BatfishServiceSessionCacheTests(unittest.IsolatedAsyncioTestCase):
    """Proves the (host, port, network) cache design actually prevents
    duplicate/racing session setup -- see doc/BATFISH_INTEGRATION.md
    "Session caching and concurrency safety".
    """

    async def asyncSetUp(self) -> None:
        self.service = BatfishService()
        self.session_patcher = patch("services.batfish.client.Session")
        self.mock_session_cls = self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

    async def test_concurrent_calls_same_network_construct_session_once(self) -> None:
        mock_instance = MagicMock()
        self.mock_session_cls.return_value = mock_instance

        results = await asyncio.gather(
            *[
                self.service._get_session(_connection(), "manus-workflow-1")
                for _ in range(10)
            ]
        )

        self.mock_session_cls.assert_called_once_with(host="batfish", port=9996)
        mock_instance.set_network.assert_called_once_with("manus-workflow-1")
        self.assertTrue(all(r is mock_instance for r in results))

    async def test_different_networks_get_independent_sessions(self) -> None:
        instance_a = MagicMock()
        instance_b = MagicMock()
        self.mock_session_cls.side_effect = [instance_a, instance_b]

        session_a = await self.service._get_session(_connection(), "manus-workflow-1")
        session_b = await self.service._get_session(_connection(), "manus-workflow-2")

        self.assertEqual(self.mock_session_cls.call_count, 2)
        self.assertIsNot(session_a, session_b)
        instance_a.set_network.assert_called_once_with("manus-workflow-1")
        instance_b.set_network.assert_called_once_with("manus-workflow-2")

    async def test_different_host_port_gets_independent_session(self) -> None:
        instance_a = MagicMock()
        instance_b = MagicMock()
        self.mock_session_cls.side_effect = [instance_a, instance_b]

        await self.service._get_session(_connection(host="batfish"), "net")
        await self.service._get_session(_connection(host="127.0.0.1"), "net")

        self.assertEqual(self.mock_session_cls.call_count, 2)


class BatfishServiceHealthCheckTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = BatfishService()
        self.session_patcher = patch("services.batfish.client.Session")
        self.mock_session_cls = self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)

    async def test_check_health_returns_networks_not_cached(self) -> None:
        instance = MagicMock()
        instance.list_networks.return_value = ["manus-workflow-1"]
        self.mock_session_cls.return_value = instance

        result = await self.service.check_health(_connection())

        self.assertEqual(result, ["manus-workflow-1"])
        instance.set_network.assert_not_called()
        self.assertEqual(self.service._sessions, {})

    async def test_check_health_wraps_batfish_exception(self) -> None:
        instance = MagicMock()
        instance.list_networks.side_effect = BatfishException("coordinator down")
        self.mock_session_cls.return_value = instance

        with self.assertRaises(BatfishAPIError):
            await self.service.check_health(_connection())

    async def test_check_health_wraps_connection_error(self) -> None:
        self.mock_session_cls.side_effect = ConnectionError("refused")

        with self.assertRaises(BatfishAPIError):
            await self.service.check_health(_connection())


class BatfishServiceSnapshotTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = BatfishService()
        self.session_patcher = patch("services.batfish.client.Session")
        self.mock_session_cls = self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)
        self.instance = MagicMock()
        self.mock_session_cls.return_value = self.instance

    async def test_init_snapshot_returns_name(self) -> None:
        self.instance.init_snapshot.return_value = "run-42"

        result = await self.service.init_snapshot(
            _connection(),
            batfish_network="manus-workflow-1",
            snapshot_name="run-42",
            snapshot_dir="/tmp/snap",
        )

        self.assertEqual(result, "run-42")
        self.instance.init_snapshot.assert_called_once_with(
            "/tmp/snap", name="run-42", overwrite=True
        )

    async def test_init_snapshot_wraps_failure(self) -> None:
        self.instance.init_snapshot.side_effect = BatfishException("bad snapshot")
        with self.assertRaises(BatfishAPIError):
            await self.service.init_snapshot(
                _connection(),
                batfish_network="manus-workflow-1",
                snapshot_name="run-42",
                snapshot_dir="/tmp/snap",
            )

    async def test_list_snapshots_delegates_to_session(self) -> None:
        self.instance.list_snapshots.return_value = ["run-1", "run-2"]
        result = await self.service.list_snapshots(
            _connection(), batfish_network="manus-workflow-1"
        )
        self.assertEqual(result, ["run-1", "run-2"])
        self.instance.list_snapshots.assert_called_once_with(verbose=False)

    async def test_list_snapshots_with_metadata_requests_verbose(self) -> None:
        verbose_payload = [
            {"name": "run-1", "metadata": {"creationTimestamp": "2026-09-12T16:00:00.000Z"}},
            {"name": "run-2", "metadata": {"creationTimestamp": "2026-09-12T17:00:00.000Z"}},
        ]
        self.instance.list_snapshots.return_value = verbose_payload
        result = await self.service.list_snapshots_with_metadata(
            _connection(), batfish_network="manus-workflow-1"
        )
        self.assertEqual(result, verbose_payload)
        self.instance.list_snapshots.assert_called_once_with(verbose=True)

    async def test_list_snapshots_with_metadata_wraps_failure(self) -> None:
        self.instance.list_snapshots.side_effect = BatfishException("coordinator down")
        with self.assertRaises(BatfishAPIError):
            await self.service.list_snapshots_with_metadata(
                _connection(), batfish_network="manus-workflow-1"
            )

    async def test_delete_snapshot_delegates_to_session(self) -> None:
        await self.service.delete_snapshot(
            _connection(), batfish_network="manus-workflow-1", snapshot_name="run-1"
        )
        self.instance.delete_snapshot.assert_called_once_with("run-1")


class BatfishServiceQuestionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.service = BatfishService()
        self.session_patcher = patch("services.batfish.client.Session")
        self.mock_session_cls = self.session_patcher.start()
        self.addCleanup(self.session_patcher.stop)
        self.instance = MagicMock()
        self.mock_session_cls.return_value = self.instance

    def _stub_question(self, rows_json: str) -> MagicMock:
        mock_frame = MagicMock()
        mock_frame.to_json.return_value = rows_json
        mock_answer = MagicMock()
        mock_answer.frame.return_value = mock_frame
        mock_question_call = MagicMock()
        mock_question_call.answer.return_value = mock_answer
        mock_question = MagicMock(return_value=mock_question_call)
        return mock_question

    async def test_routes_returns_parsed_rows(self) -> None:
        self.instance.q.routes = self._stub_question('[{"Node": "r1"}]')

        result = await self.service.routes(
            _connection(), batfish_network="net", snapshot="snap", nodes="R1"
        )

        self.assertEqual(result, [{"Node": "r1"}])
        self.instance.q.routes.assert_called_once_with(nodes="R1")

    async def test_routes_omits_none_params(self) -> None:
        self.instance.q.routes = self._stub_question("[]")

        await self.service.routes(
            _connection(), batfish_network="net", snapshot="snap", nodes="R1", network_prefix=None
        )

        self.instance.q.routes.assert_called_once_with(nodes="R1")

    async def test_reachability_passes_snapshot_explicitly(self) -> None:
        self.instance.q.reachability = self._stub_question("[]")

        await self.service.reachability(
            _connection(),
            batfish_network="net",
            snapshot="run-42",
            pathConstraints={"startLocation": "R1"},
        )

        call_answer = self.instance.q.reachability.return_value.answer
        call_answer.assert_called_once_with(snapshot="run-42")

    async def test_test_filters_wraps_batfish_exception(self) -> None:
        self.instance.q.testFilters = MagicMock(side_effect=BatfishException("bad question"))

        with self.assertRaises(BatfishAPIError):
            await self.service.test_filters(
                _connection(), batfish_network="net", snapshot="snap", nodes="R1", filters="ACL"
            )


if __name__ == "__main__":
    unittest.main()
