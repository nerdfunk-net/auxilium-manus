"""``BatfishPreviewService.run_snapshot_devices`` and the ``ipOwners`` query path.

BatfishService is mocked; nothing here talks to a coordinator.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from models.batfish import MAX_PREVIEW_ROWS, BatfishGenericQueryRequest
from services.batfish.client import PREVIEW_ROW_LIMIT
from services.batfish.common.exceptions import BatfishAPIError
from services.batfish.credentials import BatfishConnection
from services.batfish.preview_service import MAX_IP_OWNER_ROWS, BatfishPreviewService


def _service() -> tuple[BatfishPreviewService, MagicMock]:
    sources = MagicMock()
    sources.resolve_connection.return_value = BatfishConnection(host="batfish", port=9996)
    batfish = MagicMock()
    batfish.list_networks = AsyncMock(return_value=["net"])
    batfish.node_properties = AsyncMock(
        return_value=[{"Node": "lab", "Configuration_Format": "CISCO_IOS"}]
    )
    batfish.generic_question = AsyncMock(
        return_value=[
            {"Node": "lab", "IP": "1.1.1.1", "Mask": 32},
            {"Node": "r1", "IP": "2.2.2.2", "Mask": 32},
        ]
    )
    return BatfishPreviewService(sources, batfish), batfish


class SnapshotDevicesTests(unittest.IsolatedAsyncioTestCase):
    async def test_asks_node_properties_for_two_columns_and_ip_owners_once(self) -> None:
        service, batfish = _service()

        result = await service.run_snapshot_devices("lab", "net", " run-7 ", None, with_ips=True)

        kwargs = batfish.node_properties.await_args.kwargs
        self.assertEqual(kwargs["properties"], "Configuration_Format, Domain_Name")
        self.assertEqual(kwargs["snapshot"], "run-7")
        self.assertEqual(batfish.generic_question.await_args.kwargs["question_name"], "ipOwners")
        self.assertEqual(result.snapshot, "run-7")
        self.assertEqual(len(result.node_rows), 1)
        self.assertEqual(len(result.ip_rows), 2)
        self.assertEqual(result.unavailable, {})

    async def test_without_ips_the_ip_question_is_not_asked(self) -> None:
        service, batfish = _service()

        result = await service.run_snapshot_devices("lab", "net", "run-7", None, with_ips=False)

        batfish.generic_question.assert_not_awaited()
        self.assertEqual(result.ip_rows, [])

    async def test_a_node_filter_goes_to_node_properties_and_filters_the_ip_rows(self) -> None:
        service, batfish = _service()

        result = await service.run_snapshot_devices("lab", "net", "run-7", "lab", with_ips=True)

        self.assertEqual(batfish.node_properties.await_args.kwargs["nodes"], "lab")
        self.assertEqual([r["Node"] for r in result.ip_rows], ["lab"])

    async def test_a_failing_ip_question_is_reported_and_the_devices_still_answer(self) -> None:
        service, batfish = _service()
        batfish.generic_question = AsyncMock(side_effect=BatfishAPIError("boom"))

        result = await service.run_snapshot_devices("lab", "net", "run-7", None, with_ips=True)

        self.assertEqual(list(result.unavailable), ["ips"])
        self.assertEqual(len(result.node_rows), 1)

    async def test_without_devices_the_whole_answer_fails(self) -> None:
        service, batfish = _service()
        batfish.node_properties = AsyncMock(side_effect=BatfishAPIError("boom"))

        with self.assertRaises(BatfishAPIError):
            await service.run_snapshot_devices("lab", "net", "run-7", None, with_ips=True)

    async def test_the_ip_question_may_return_more_rows_than_a_preview(self) -> None:
        """The rows are aggregated, not shown: the preview cap must not cut the counts."""
        service, batfish = _service()
        seen: list[int | None] = []

        async def ip_owners(*_: object, **__: object) -> list[dict[str, object]]:
            seen.append(PREVIEW_ROW_LIMIT.get())
            filler = [{"Node": "r1", "IP": f"10.{n // 250}.{n % 250}.1"} for n in range(6000)]
            return [*filler, {"Node": "lab", "IP": "9.9.9.9", "Mask": 32}]

        batfish.generic_question = AsyncMock(side_effect=ip_owners)
        PREVIEW_ROW_LIMIT.set(MAX_PREVIEW_ROWS)  # what the reader sets around the call

        result = await service.run_snapshot_devices("lab", "net", "run-7", "lab", with_ips=True)

        self.assertEqual(seen, [MAX_IP_OWNER_ROWS])
        self.assertEqual(PREVIEW_ROW_LIMIT.get(), MAX_PREVIEW_ROWS)  # restored afterwards
        self.assertEqual([r["IP"] for r in result.ip_rows], ["9.9.9.9"])  # past row 5000: kept
        self.assertEqual(result.truncated_sections, ())

    async def test_sections_cut_at_the_aggregation_cap_are_named(self) -> None:
        service, batfish = _service()
        batfish.generic_question = AsyncMock(
            return_value=[{"Node": "lab", "IP": "1.1.1.1"}] * (MAX_IP_OWNER_ROWS + 1)
        )

        result = await service.run_snapshot_devices("lab", "net", "run-7", None, with_ips=True)

        self.assertEqual(result.truncated_sections, ("ips",))
        self.assertEqual(len(result.ip_rows), MAX_IP_OWNER_ROWS)

    async def test_the_newest_snapshot_is_used_when_none_is_named(self) -> None:
        service, batfish = _service()
        batfish.list_snapshots_with_metadata = AsyncMock(
            return_value=[
                {"name": "old", "metadata": {"creationTimestamp": "2026-01-01T00:00:00Z"}},
                {"name": "new", "metadata": {"creationTimestamp": "2026-02-01T00:00:00Z"}},
            ]
        )

        result = await service.run_snapshot_devices("lab", "net", None, None, with_ips=True)

        self.assertEqual(result.snapshot, "new")

    async def test_ip_owners_is_an_allow_listed_generic_question(self) -> None:
        service, batfish = _service()

        result = await service.run_generic(
            "lab",
            BatfishGenericQueryRequest(
                network="net", snapshot="s", question="ipOwners", params={"ips": "10.0.0.0/24"}
            ),
        )

        self.assertTrue(result.success)
        self.assertEqual(batfish.generic_question.await_args.kwargs["ips"], "10.0.0.0/24")


class IpOwnersTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_question_gets_ips_and_duplicates_but_never_a_node_parameter(self) -> None:
        service, batfish = _service()

        await service.run_ip_owners("lab", "net", "run-7", "10.0.0.0/24", True, "lab")

        kwargs = batfish.generic_question.await_args.kwargs
        self.assertEqual(kwargs["question_name"], "ipOwners")
        self.assertEqual(kwargs["ips"], "10.0.0.0/24")
        self.assertIs(kwargs["duplicatesOnly"], True)
        self.assertNotIn("nodes", kwargs)

    async def test_no_filters_means_no_parameters(self) -> None:
        service, batfish = _service()

        await service.run_ip_owners("lab", "net", "run-7", None, False, None)

        kwargs = batfish.generic_question.await_args.kwargs
        self.assertEqual(set(kwargs) - {"batfish_network", "snapshot", "question_name"}, set())

    async def test_the_node_filter_runs_before_the_response_cap(self) -> None:
        """A device whose rows sit past the first 5000 of the snapshot must still be found."""
        service, batfish = _service()
        rows = [{"Node": "r1", "IP": f"10.{n // 250}.{n % 250}.1"} for n in range(6000)]
        rows.append({"Node": "lab", "IP": "9.9.9.9"})
        batfish.generic_question = AsyncMock(return_value=rows)

        result = await service.run_ip_owners("lab", "net", "run-7", None, False, "LAB")

        self.assertEqual([r["IP"] for r in result.rows], ["9.9.9.9"])
        self.assertFalse(result.truncated)

    async def test_duplicates_with_a_node_filter_keep_every_owner_of_the_address(self) -> None:
        service, batfish = _service()
        batfish.generic_question = AsyncMock(
            return_value=[
                {"Node": "lab", "Interface": "Gi0", "IP": "10.0.0.1"},
                {"Node": "r1", "Interface": "Gi1", "IP": "10.0.0.1"},
                {"Node": "r2", "Interface": "Gi2", "IP": "10.0.9.9"},
                {"Node": "r3", "Interface": "Gi3", "IP": "10.0.9.9"},
            ]
        )

        result = await service.run_ip_owners("lab", "net", "run-7", None, True, "lab")

        # the conflict, both sides
        self.assertEqual([r["Node"] for r in result.rows], ["lab", "r1"])

    async def test_a_cut_at_the_aggregation_cap_is_flagged(self) -> None:
        service, batfish = _service()
        batfish.generic_question = AsyncMock(
            return_value=[{"Node": "lab", "IP": "1.1.1.1"}] * (MAX_IP_OWNER_ROWS + 1)
        )

        result = await service.run_ip_owners("lab", "net", "run-7", None, False, None)

        self.assertTrue(result.truncated)

    async def test_the_row_cap_is_restored_after_the_call(self) -> None:
        service, _ = _service()
        PREVIEW_ROW_LIMIT.set(MAX_PREVIEW_ROWS)

        await service.run_ip_owners("lab", "net", "run-7", None, False, None)

        self.assertEqual(PREVIEW_ROW_LIMIT.get(), MAX_PREVIEW_ROWS)


class RealAnswerCapTests(unittest.IsolatedAsyncioTestCase):
    """Through the real ``BatfishService._answer`` (``frame.head(limit + 1)``), not a stub.

    The review's case: a snapshot with more than 5000 addresses, and a device whose rows sit
    after the first 5000 of the snapshot-wide ``ipOwners`` answer.
    """

    def _service(self, ip_frame):
        import types

        import pandas as pd

        from services.batfish.client import BatfishService

        nodes = pd.DataFrame([{"Node": "lab", "Configuration_Format": "CISCO_IOS"}])

        def question(frame):
            return lambda **_: types.SimpleNamespace(answer=lambda **__: _Frame(frame))

        class _Frame:
            def __init__(self, frame):
                self._frame = frame

            def frame(self):
                return self._frame

        session = types.SimpleNamespace(
            q=types.SimpleNamespace(nodeProperties=question(nodes), ipOwners=question(ip_frame))
        )
        batfish = BatfishService()
        batfish._get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
        batfish.list_networks = AsyncMock(return_value=["net"])  # type: ignore[method-assign]
        sources = MagicMock()
        sources.resolve_connection.return_value = BatfishConnection(host="batfish", port=9996)
        return BatfishPreviewService(sources, batfish)

    def _frame(self, filler: int):
        import pandas as pd

        rows = [
            {"Node": "r1", "Interface": "Gi0", "IP": f"10.{n // 250}.{n % 250}.1", "Mask": 24}
            for n in range(filler)
        ]
        rows.append(
            {"Node": "lab", "Interface": "Gi1", "IP": "9.9.9.9", "Mask": 32, "Active": True}
        )
        return pd.DataFrame(rows)

    async def test_a_device_after_the_first_five_thousand_rows_keeps_its_addresses(self) -> None:
        service = self._service(self._frame(6000))
        PREVIEW_ROW_LIMIT.set(MAX_PREVIEW_ROWS)  # what the reader sets around the call

        result = await service.run_snapshot_devices("lab", "net", "run-7", "lab", with_ips=True)

        self.assertEqual([r["IP"] for r in result.ip_rows], ["9.9.9.9"])
        self.assertEqual(result.truncated_sections, ())

    async def test_ip_owners_for_that_device_is_found_too(self) -> None:
        service = self._service(self._frame(6000))
        PREVIEW_ROW_LIMIT.set(MAX_PREVIEW_ROWS)

        result = await service.run_ip_owners("lab", "net", "run-7", None, False, "lab")

        self.assertEqual([r["IP"] for r in result.rows], ["9.9.9.9"])
        self.assertFalse(result.truncated)


class RealNodePropertiesFactsTests(unittest.IsolatedAsyncioTestCase):
    """Device facts from a raw ``nodeProperties`` pandas frame, through the real
    ``BatfishService._answer`` and the preview service, to the tool's shaping."""

    async def test_a_raw_frame_becomes_the_same_facts_the_tool_shapes_today(self) -> None:
        import types

        import pandas as pd

        from services.ai_assistant.batfish_reader import DbBatfishReader
        from services.ai_assistant.tools.batfish_shaping import shape_facts
        from services.batfish.client import BatfishService

        frame = pd.DataFrame(
            [
                {
                    "Node": "lab",
                    "Hostname": "lab",
                    "Logging_Servers": ["10.9.9.9"],
                    "NTP_Servers": [],
                    "VRFs": ["default", "~internal"],
                    "Interfaces": ["Gi0/1"],
                }
            ]
        )
        asked: list[dict[str, object]] = []

        def node_properties(**kwargs: object):
            asked.append(kwargs)
            return types.SimpleNamespace(
                answer=lambda **_: types.SimpleNamespace(frame=lambda: frame)
            )

        session = types.SimpleNamespace(q=types.SimpleNamespace(nodeProperties=node_properties))
        batfish = BatfishService()
        batfish._get_session = AsyncMock(return_value=session)  # type: ignore[method-assign]
        batfish.list_networks = AsyncMock(return_value=["net"])  # type: ignore[method-assign]
        sources = MagicMock()
        sources.resolve_connection.return_value = BatfishConnection(host="batfish", port=9996)
        preview = BatfishPreviewService(sources, batfish)

        response = await DbBatfishReader._run_facts(
            preview,
            "lab",
            "net",
            "run-7",
            {"nodes": "lab", "facts": "Hostname,Logging_Servers,VRFs"},
        )

        assert asked == [{"nodes": "lab", "properties": "Hostname, Logging_Servers, VRFs"}]
        rows = [{"Node": n, "Facts": f} for n, f in (response.facts_by_node or {}).items()]
        assert shape_facts(rows, ["Hostname", "Logging_Servers", "VRFs"]) == [
            {"Node": "lab", "Hostname": "lab", "Logging_Servers": ["10.9.9.9"], "VRFs": ["default"]}
        ]
