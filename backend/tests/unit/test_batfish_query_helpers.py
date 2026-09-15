"""Tests for services.batfish.query_helpers.query_generic -- the allow-list
gate for the ad-hoc "Custom Question..." surface. BatfishService is mocked
throughout; these never talk to a real coordinator (see the "Template Editor
integration" section of doc/BATFISH_INTEGRATION.md for how the allow-list
itself was verified against one).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from services.batfish.credentials import BatfishConnection
from services.batfish.query_helpers import GENERIC_QUESTION_ALLOWLIST, query_generic


def _connection() -> BatfishConnection:
    return BatfishConnection(host="batfish", port=9996)


class QueryGenericTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_non_allowlisted_question(self) -> None:
        batfish = MagicMock()
        batfish.generic_question = AsyncMock()

        with self.assertRaises(ValueError):
            await query_generic(
                batfish,
                _connection(),
                batfish_network="net",
                snapshot="snap",
                question_name="deleteEverything",
            )
        batfish.generic_question.assert_not_awaited()

    async def test_allowlisted_question_forwards_to_service(self) -> None:
        batfish = MagicMock()
        batfish.generic_question = AsyncMock(return_value=[{"Node": "r1"}])
        question_name = next(iter(GENERIC_QUESTION_ALLOWLIST))

        result = await query_generic(
            batfish,
            _connection(),
            batfish_network="net",
            snapshot="snap",
            question_name=question_name,
            params={"nodes": "R1", "blank": "   "},
        )

        self.assertEqual(result, [{"Node": "r1"}])
        batfish.generic_question.assert_awaited_once_with(
            _connection(),
            batfish_network="net",
            snapshot="snap",
            question_name=question_name,
            nodes="R1",
        )

    async def test_blank_and_none_params_are_dropped(self) -> None:
        batfish = MagicMock()
        batfish.generic_question = AsyncMock(return_value=[])
        question_name = next(iter(GENERIC_QUESTION_ALLOWLIST))

        await query_generic(
            batfish,
            _connection(),
            batfish_network="net",
            snapshot="snap",
            question_name=question_name,
            params=None,
        )

        batfish.generic_question.assert_awaited_once_with(
            _connection(),
            batfish_network="net",
            snapshot="snap",
            question_name=question_name,
        )


if __name__ == "__main__":
    unittest.main()
