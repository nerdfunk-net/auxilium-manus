from __future__ import annotations

import time

import pytest

from services.ai_assistant.released_run_builder import ProposedDevice
from services.ai_assistant.workflow_run_token import (
    InvalidRunTokenError,
    issue_run_token,
    verify_run_token,
)

D1 = ProposedDevice(ip="10.0.0.1", name="sw1", network_driver="cisco_xe", platform="ios")
D2 = ProposedDevice(ip="10.0.0.2", in_inventory=False)


def _issue(**kw):
    args = {
        "user_id": 7,
        "workflow_id": 3,
        "run_inputs": {"a": 1},
        "devices": [D1, D2],
        "stamp": "stamp-a",
    }
    return issue_run_token(**{**args, **kw})


def test_round_trip() -> None:
    token, expires = _issue()
    grant = verify_run_token(token, user_id=7)
    assert (grant.workflow_id, grant.run_inputs, grant.devices) == (3, {"a": 1}, (D1, D2))
    assert grant.expires_at == expires


def test_the_stamp_and_a_fresh_one_time_id_ride_along() -> None:
    first, _ = _issue()
    second, _ = _issue()
    a, b = verify_run_token(first, user_id=7), verify_run_token(second, user_id=7)
    assert a.stamp == "stamp-a"
    assert a.token_id != b.token_id and len(a.token_id) == 32


def test_other_user_is_refused() -> None:
    token, _ = _issue()
    with pytest.raises(InvalidRunTokenError):
        verify_run_token(token, user_id=8)


def test_expired_is_refused() -> None:
    token, _ = _issue(now=time.time() - 10_000)
    with pytest.raises(InvalidRunTokenError):
        verify_run_token(token, user_id=7)


def test_tampered_payload_is_refused() -> None:
    token, _ = _issue()
    other, _ = _issue(devices=[ProposedDevice(ip="6.6.6.6", in_inventory=False)])
    forged = other.split(".")[0] + "." + token.split(".")[1]
    with pytest.raises(InvalidRunTokenError):
        verify_run_token(forged, user_id=7)


@pytest.mark.parametrize("bad", [None, 5, "", "nodot", "a.b.c", "x" * 20000, "!!.??"])
def test_garbage_is_refused(bad: object) -> None:
    with pytest.raises(InvalidRunTokenError):
        verify_run_token(bad, user_id=7)
