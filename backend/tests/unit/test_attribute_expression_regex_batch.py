"""Tests for the batched, isolated regex adapter used by attribute expressions."""

from __future__ import annotations

import unittest

from services.workflow_context.attribute_expression.regex_batch import resolve_regex_batch


class ResolveRegexBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_and_find_modes(self) -> None:
        keys = {
            ("sw12", r"sw\d+", "full"),
            ("xsw12", r"sw\d+", "full"),
            ("xsw12", r"sw\d+", "find"),
            ("router", r"sw\d+", "find"),
        }
        results = await resolve_regex_batch(keys)
        self.assertEqual(
            results,
            {
                ("sw12", r"sw\d+", "full"): True,
                ("xsw12", r"sw\d+", "full"): False,
                ("xsw12", r"sw\d+", "find"): True,
                ("router", r"sw\d+", "find"): False,
            },
        )

    async def test_empty_input_spawns_nothing(self) -> None:
        self.assertEqual(await resolve_regex_batch(set()), {})

    async def test_invalid_pattern_only_spoils_its_own_answer(self) -> None:
        results = await resolve_regex_batch({("a", "(", "full"), ("a", "a", "full")})
        self.assertEqual(results[("a", "(", "full")], "invalid")
        self.assertIs(results[("a", "a", "full")], True)

    async def test_catastrophic_pattern_is_stopped_and_the_rest_still_answered(self) -> None:
        slow = ("a" * 40 + "!", r"(a+)+$", "full")
        fine = ("sw1", r"sw\d", "full")
        results = await resolve_regex_batch({slow, fine})
        self.assertEqual(results[slow], "stopped")
        self.assertIs(results[fine], True)

    async def test_empty_pattern_is_invalid_for_find_and_matches(self) -> None:
        results = await resolve_regex_batch({("hello", "", "find"), ("hello", "", "full")})
        self.assertEqual(set(results.values()), {"invalid"})

    async def test_errors_do_not_echo_pattern_or_text(self) -> None:
        results = await resolve_regex_batch({("secret-text", "(", "full")})
        self.assertNotIn("secret-text", repr(results.values()))


if __name__ == "__main__":
    unittest.main()
