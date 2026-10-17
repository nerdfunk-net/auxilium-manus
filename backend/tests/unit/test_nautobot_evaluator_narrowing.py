"""AND operations narrow on the Redis indexes first.

role/status/device_type/manufacturer/platform equality conditions of an AND are
resolved to device ids from the indexes (nothing parsed), intersected, and only the
surviving devices are fetched. Every other condition of that AND (name contains,
tag, custom field, ...) then runs over just those devices instead of the whole fleet.
Real RedisCacheService on fakeredis, real query service + evaluator.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis

from models.sources_nautobot import LogicalCondition, LogicalOperation
from services.cache.redis_cache_service import RedisCacheService
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.evaluator import NautobotSourceEvaluator
from services.sources.nautobot.query_service import NautobotSourceQueryService

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")


def _gql(did: str, role: str | None, status: str = "Active", tags=(), **over) -> dict:
    d = {
        "id": did,
        "name": f"dev-{did}",
        "serial": "SN",
        "_custom_field_data": {},
        "primary_ip4": {"address": "10.0.0.1/24"},
        "status": {"name": status},
        "device_type": {"model": "C9300", "manufacturer": {"name": "Cisco"}},
        "role": {"name": role} if role else None,
        "location": {"name": "dc1"},
        "tags": [{"name": t} for t in tags],
        "platform": {"name": "ios", "network_driver": "ios"},
    }
    d.update(over)
    return d


_FLEET = [
    _gql("a", "leaf", tags=["prod"]),
    _gql("b", "server", status="Planned"),
    _gql("c", "server", tags=["prod"]),
    _gql("d", None),
    _gql("e", "server", tags=["prod", "dmz"]),
    _gql("f", "spine"),
]


def _cache() -> RedisCacheService:
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    with patch("services.cache.redis_cache_service.redis.from_url", return_value=fake):
        return RedisCacheService("redis://localhost:6379/0", key_prefix="test-cache")


def _cond(field: str, operator: str, value: str) -> LogicalCondition:
    return LogicalCondition(field=field, operator=operator, value=value)


def _and(*conditions: LogicalCondition, nested=()) -> LogicalOperation:
    return LogicalOperation(
        operation_type="AND", conditions=list(conditions), nested_operations=list(nested)
    )


class NarrowingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cache = _cache()
        self.nautobot = MagicMock()
        self.nautobot.graphql_query = AsyncMock(return_value={"data": {"devices": _FLEET}})
        writer = NautobotSourceQueryService(self.nautobot, _CREDS, self.cache)
        await writer.refresh_bulk_cache()
        self.nautobot.graphql_query.reset_mock()
        # a fresh service per "request"
        self.qs = NautobotSourceQueryService(self.nautobot, _CREDS, self.cache)
        self.evaluator = NautobotSourceEvaluator(self.qs)

    async def _run(self, op: LogicalOperation):
        ids, count, data = await self.evaluator._execute_operation(op)
        self.assertEqual(set(data) >= ids, True)  # every result id has its device data
        return ids, count, data

    async def test_and_of_indexed_conditions_parses_only_the_intersection(self) -> None:
        with (
            patch.object(self.cache, "hvals_json") as hvals,
            patch.object(self.cache, "hmget_json", wraps=self.cache.hmget_json) as hmget,
        ):
            ids, _, _ = await self._run(
                _and(_cond("role", "equals", "server"), _cond("status", "equals", "Active"))
            )
        self.assertEqual(ids, {"c", "e"})
        hvals.assert_not_called()
        hmget.assert_called_once()
        (_, fields), _ = hmget.call_args
        self.assertEqual(sorted(fields), ["c", "e"])

    async def test_stale_index_ids_never_select_a_device_that_no_longer_matches(self) -> None:
        # indexes still say "c" is an Active server, the data hash already says leaf
        key = f"test-cache:{self.qs._bulk_cache_key}"
        body = json.loads(self.cache._redis.hget(key, "c"))
        self.cache._redis.hset(key, "c", json.dumps({**body, "role": "leaf"}))
        ids, _, _ = await self._run(
            _and(_cond("role", "equals", "server"), _cond("status", "equals", "Active"))
        )
        self.assertEqual(ids, {"e"})

    async def test_failed_index_read_does_not_turn_an_and_into_an_empty_result(self) -> None:
        real_hget = self.cache._redis.hget

        def flaky_hget(key, field):
            if ":idx:" in key:
                raise ConnectionError("dropped")
            return real_hget(key, field)

        with patch.object(self.cache._redis, "hget", side_effect=flaky_hget):
            ids, _, _ = await self._run(
                _and(_cond("role", "equals", "server"), _cond("status", "equals", "Active"))
            )
        self.assertEqual(ids, {"c", "e"})

    async def test_scan_conditions_only_look_at_the_narrowed_devices(self) -> None:
        with (
            patch.object(self.cache, "hvals_json") as hvals,
            patch.object(self.cache, "hmget_json", wraps=self.cache.hmget_json) as hmget,
        ):
            ids, _, _ = await self._run(
                _and(_cond("role", "equals", "server"), _cond("tag", "equals", "dmz"))
            )
        self.assertEqual(ids, {"e"})
        hvals.assert_not_called()
        (_, fields), _ = hmget.call_args
        self.assertEqual(sorted(fields), ["b", "c", "e"])  # the servers, nothing else

    async def test_name_contains_runs_over_the_narrowed_devices(self) -> None:
        ids, _, _ = await self._run(
            _and(_cond("role", "equals", "server"), _cond("name", "contains", "dev-c"))
        )
        self.assertEqual(ids, {"c"})

    async def test_not_equals_includes_devices_without_a_value(self) -> None:
        ids, _, _ = await self._run(
            _and(_cond("role", "not_equals", "server"), _cond("status", "equals", "Active"))
        )
        self.assertEqual(ids, {"a", "d", "f"})  # "d" has no role at all

    async def test_status_not_equals_matches_the_old_client_side_negation(self) -> None:
        ids, _, _ = await self._run(
            _and(_cond("role", "equals", "server"), _cond("status", "not_equals", "Active"))
        )
        self.assertEqual(ids, {"b"})

    async def test_no_match_short_circuits_without_running_other_conditions(self) -> None:
        location = AsyncMock(return_value=[])
        with patch.dict(self.evaluator.field_to_query_map, {"location": location}):
            ids, _, data = await self._run(
                _and(_cond("role", "equals", "firewall"), _cond("location", "equals", "dc1"))
            )
        self.assertEqual((ids, data), (set(), {}))
        location.assert_not_awaited()

    async def test_non_indexed_conditions_that_leave_the_cache_still_intersect(self) -> None:
        dev_c = await self.qs._devices_by_ids({"c"})
        with patch.dict(
            self.evaluator.field_to_query_map, {"location": AsyncMock(return_value=dev_c)}
        ):
            ids, _, _ = await self._run(
                _and(_cond("role", "equals", "server"), _cond("location", "equals", "dc1"))
            )
        self.assertEqual(ids, {"c"})

    async def test_nested_groups_run_over_the_narrowed_devices(self) -> None:
        nested = LogicalOperation(
            operation_type="OR",
            conditions=[_cond("tag", "equals", "dmz"), _cond("name", "equals", "dev-b")],
        )
        with patch.object(self.cache, "hvals_json") as hvals:
            ids, _, _ = await self._run(_and(_cond("role", "equals", "server"), nested=[nested]))
        self.assertEqual(ids, {"b", "e"})
        hvals.assert_not_called()

    async def test_nested_not_group_is_subtracted(self) -> None:
        not_group = LogicalOperation(
            operation_type="NOT", conditions=[_cond("tag", "equals", "dmz")]
        )
        ids, _, _ = await self._run(_and(_cond("role", "equals", "server"), nested=[not_group]))
        self.assertEqual(ids, {"b", "c"})

    async def test_the_full_list_is_restored_after_the_operation(self) -> None:
        await self._run(_and(_cond("role", "equals", "server"), _cond("tag", "equals", "dmz")))
        self.assertIsNone(self.qs._devices_cache)

    async def test_or_operations_are_not_narrowed(self) -> None:
        op = LogicalOperation(
            operation_type="OR",
            conditions=[_cond("role", "equals", "leaf"), _cond("role", "equals", "spine")],
        )
        with patch.object(self.qs, "_ids_by_attribute", new=AsyncMock()) as ids_by_attribute:
            ids, _, _ = await self._run(op)
        self.assertEqual(ids, {"a", "f"})
        ids_by_attribute.assert_not_awaited()

    async def test_and_without_indexed_conditions_is_unchanged(self) -> None:
        ids, _, _ = await self._run(
            _and(_cond("tag", "equals", "prod"), _cond("name", "contains", "dev-"))
        )
        self.assertEqual(ids, {"a", "c", "e"})

    async def test_contains_on_an_indexed_field_is_not_narrowed(self) -> None:
        # "contains" is not supported for these fields (exact match + warning): keep that path
        with patch.object(self.qs, "_ids_by_attribute", new=AsyncMock()) as ids_by_attribute:
            ids, _, _ = await self._run(
                _and(_cond("role", "contains", "server"), _cond("tag", "equals", "prod"))
            )
        self.assertEqual(ids, {"c", "e"})
        ids_by_attribute.assert_not_awaited()

    async def test_narrowing_failure_falls_back_to_the_per_condition_path(self) -> None:
        with patch.object(
            self.qs, "_ids_by_attribute", new=AsyncMock(side_effect=RuntimeError("boom"))
        ):
            ids, _, _ = await self._run(
                _and(_cond("role", "equals", "server"), _cond("status", "equals", "Active"))
            )
        self.assertEqual(ids, {"c", "e"})

    async def test_cold_cache_gives_the_same_answer_via_live_data(self) -> None:
        qs = NautobotSourceQueryService(self.nautobot, _CREDS, _cache())
        ids, _, _ = await NautobotSourceEvaluator(qs)._execute_operation(
            _and(_cond("role", "equals", "server"), _cond("status", "equals", "Active"))
        )
        self.assertEqual(ids, {"c", "e"})

    async def test_operations_count_includes_the_indexed_conditions(self) -> None:
        _, count, _ = await self._run(
            _and(_cond("role", "equals", "server"), _cond("status", "equals", "Active"))
        )
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
