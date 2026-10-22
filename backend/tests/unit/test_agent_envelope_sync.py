"""The agent's standalone envelope.py, its test vectors and its limits must not drift from ours."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from core.secret_policy import MIN_AGENT_SECRET_LENGTH

REPO = Path(__file__).resolve().parents[3]
BACKEND_ENVELOPE = REPO / "backend" / "services" / "agents" / "envelope.py"
AGENT_ENVELOPE = REPO / "agent" / "manus_agent" / "envelope.py"
BACKEND_VECTORS = Path(__file__).parent / "fixtures" / "agent_envelope_vectors.json"
AGENT_VECTORS = REPO / "agent" / "tests" / "fixtures" / "agent_envelope_vectors.json"

# The import and the blank line after it; the agent has a constant in its place.
_BACKEND_IMPORT = "from core.secret_policy import MIN_AGENT_SECRET_LENGTH\n\n"
_AGENT_CONSTANT = re.compile(
    r"# Must equal backend/core/secret_policy\.py::MIN_AGENT_SECRET_LENGTH[^\n]*\n"
    r"MIN_AGENT_SECRET_LENGTH = \d+\n"
)


class AgentEnvelopeSyncTests(unittest.TestCase):
    def test_envelope_copies_differ_only_in_the_secret_length_constant(self) -> None:
        backend = BACKEND_ENVELOPE.read_text()
        agent = AGENT_ENVELOPE.read_text()
        self.assertIn(_BACKEND_IMPORT, backend)
        self.assertEqual(len(_AGENT_CONSTANT.findall(agent)), 1)
        self.assertEqual(
            backend.replace(_BACKEND_IMPORT, ""),
            _AGENT_CONSTANT.sub("", agent),
            "agent/manus_agent/envelope.py has drifted from backend/services/agents/envelope.py",
        )

    def test_agent_secret_length_matches_the_backend_policy(self) -> None:
        match = re.search(r"^MIN_AGENT_SECRET_LENGTH = (\d+)$", AGENT_ENVELOPE.read_text(), re.M)
        self.assertIsNotNone(match)
        self.assertEqual(int(match.group(1)), MIN_AGENT_SECRET_LENGTH)  # type: ignore[union-attr]

    def test_both_suites_run_the_same_vectors(self) -> None:
        self.assertEqual(BACKEND_VECTORS.read_bytes(), AGENT_VECTORS.read_bytes())


if __name__ == "__main__":
    unittest.main()
