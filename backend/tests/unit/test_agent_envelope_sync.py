"""The agent's standalone envelope.py, its test vectors and its limits must not drift from ours."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from core.secret_policy import MIN_AGENT_SECRET_LENGTH

REPO = Path(__file__).resolve().parents[3]
BACKEND_ENVELOPE = REPO / "backend" / "services" / "agents" / "envelope.py"
AGENT_DIRS = sorted(p for p in (REPO / "agent").iterdir() if (p / "manus_agent").is_dir())
BACKEND_VECTORS = Path(__file__).parent / "fixtures" / "agent_envelope_vectors.json"

# The import and the blank line after it; the agent has a constant in its place.
_BACKEND_IMPORT = "from core.secret_policy import MIN_AGENT_SECRET_LENGTH\n\n"
_AGENT_CONSTANT = re.compile(
    r"# Must equal backend/core/secret_policy\.py::MIN_AGENT_SECRET_LENGTH[^\n]*\n"
    r"MIN_AGENT_SECRET_LENGTH = \d+\n"
)


class AgentEnvelopeSyncTests(unittest.TestCase):
    def test_every_agent_is_checked(self) -> None:
        self.assertTrue(AGENT_DIRS, "no agent directory found under agent/")

    def test_envelope_copies_differ_only_in_the_secret_length_constant(self) -> None:
        backend = BACKEND_ENVELOPE.read_text()
        self.assertIn(_BACKEND_IMPORT, backend)
        for agent_dir in AGENT_DIRS:
            with self.subTest(agent=agent_dir.name):
                agent = (agent_dir / "manus_agent" / "envelope.py").read_text()
                self.assertEqual(len(_AGENT_CONSTANT.findall(agent)), 1)
                self.assertEqual(
                    backend.replace(_BACKEND_IMPORT, ""),
                    _AGENT_CONSTANT.sub("", agent),
                    f"agent/{agent_dir.name}/manus_agent/envelope.py has drifted from "
                    "backend/services/agents/envelope.py",
                )

    def test_agent_secret_length_matches_the_backend_policy(self) -> None:
        for agent_dir in AGENT_DIRS:
            with self.subTest(agent=agent_dir.name):
                text = (agent_dir / "manus_agent" / "envelope.py").read_text()
                match = re.search(r"^MIN_AGENT_SECRET_LENGTH = (\d+)$", text, re.M)
                self.assertIsNotNone(match)
                self.assertEqual(int(match.group(1)), MIN_AGENT_SECRET_LENGTH)  # type: ignore[union-attr]

    def test_both_suites_run_the_same_vectors(self) -> None:
        for agent_dir in AGENT_DIRS:
            with self.subTest(agent=agent_dir.name):
                vectors = agent_dir / "tests" / "fixtures" / "agent_envelope_vectors.json"
                self.assertEqual(BACKEND_VECTORS.read_bytes(), vectors.read_bytes())


if __name__ == "__main__":
    unittest.main()
