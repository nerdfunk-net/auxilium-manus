"""cap_persisted_output: the database copy of a step output is bounded."""

from __future__ import annotations

import json
import unittest

from services.execution.output_cap import TRUNCATED_KEY, cap_persisted_output


def _persisted(**parsed: object) -> dict:
    return {
        "success": {
            "devices": {"d1": {"parsed": dict(parsed), "attribute_bags": {}}},
            "metadata": {},
        }
    }


class OutputCapTests(unittest.TestCase):
    def test_small_payload_is_unchanged(self) -> None:
        persisted = _persisted(a="x", b={"k": 1})
        expected = json.loads(json.dumps(persisted))
        self.assertEqual(
            cap_persisted_output(persisted, value_max=1024, total_max=10_000), expected
        )

    def test_large_value_is_replaced_by_marker(self) -> None:
        persisted = _persisted(big="x" * 5000, small="y")
        capped = cap_persisted_output(persisted, value_max=1024, total_max=1_000_000)
        parsed = capped["success"]["devices"]["d1"]["parsed"]
        self.assertTrue(parsed["big"][TRUNCATED_KEY])
        self.assertGreater(parsed["big"]["bytes"], 5000)
        self.assertEqual(parsed["small"], "y")

    def test_total_cap_drops_largest_first(self) -> None:
        persisted = _persisted(a="a" * 800, b="b" * 600, c="c" * 400)
        capped = cap_persisted_output(persisted, value_max=1000, total_max=1200)
        parsed = capped["success"]["devices"]["d1"]["parsed"]
        self.assertTrue(parsed["a"].get(TRUNCATED_KEY))
        self.assertEqual(parsed["c"], "c" * 400)

    def test_marker_survives_json_round_trip(self) -> None:
        capped = cap_persisted_output(_persisted(big="x" * 5000), value_max=1024, total_max=10_000)
        again = json.loads(json.dumps(capped))
        self.assertEqual(again, capped)


if __name__ == "__main__":
    unittest.main()
