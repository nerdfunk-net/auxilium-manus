from __future__ import annotations

import time

import pytest

from services.ai_assistant.workflow_run_token import (
    InvalidRunTokenError,
    issue_run_token,
    verify_run_token,
)


def _issue(**kw):
    args = {"user_id": 7, "workflow_id": 3, "run_inputs": {"a": 1}, "device_ids": ["d1", "d2"]}
    return issue_run_token(**{**args, **kw})


def test_round_trip() -> None:
    token, expires = _issue()
    grant = verify_run_token(token, user_id=7)
    assert (grant.workflow_id, grant.run_inputs, grant.device_ids) == (3, {"a": 1}, ("d1", "d2"))
    assert grant.expires_at == expires


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
    other, _ = _issue(device_ids=["evil"])
    forged = other.split(".")[0] + "." + token.split(".")[1]
    with pytest.raises(InvalidRunTokenError):
        verify_run_token(forged, user_id=7)


@pytest.mark.parametrize("bad", [None, 5, "", "nodot", "a.b.c", "x" * 20000, "!!.??"])
def test_garbage_is_refused(bad: object) -> None:
    with pytest.raises(InvalidRunTokenError):
        verify_run_token(bad, user_id=7)
