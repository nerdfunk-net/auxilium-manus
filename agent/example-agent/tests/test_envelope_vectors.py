"""The agent's envelope.py must open exactly what the backend produced (shared vectors)."""

import json
from pathlib import Path

import pytest

from manus_agent.envelope import derive_http_token, open_envelope

DATA = json.loads((Path(__file__).parent / "fixtures" / "agent_envelope_vectors.json").read_text())


@pytest.mark.parametrize("vector", DATA["vectors"], ids=[v["name"] for v in DATA["vectors"]])
def test_vector_opens(vector):
    envelope = vector["envelope"]
    opened = open_envelope(
        envelope,
        secret=DATA["secret"],
        expected_agent_id=envelope["agent_id"],
        expected_direction=envelope["direction"],
        expected_command_id=envelope["command_id"],
        now=vector["now"],
    )
    assert opened.payload == vector["payload"]


def test_http_token_matches_the_backend():
    assert derive_http_token(DATA["secret"], DATA["http_token_agent_id"]) == DATA["http_token"]
