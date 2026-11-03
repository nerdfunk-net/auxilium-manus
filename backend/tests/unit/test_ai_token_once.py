import pytest
import redis

from services.ai_assistant import token_once
from services.ai_assistant.token_once import (
    ConfirmationStoreUnavailableError,
    claim,
    confirm,
    release,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.data:
            return None
        self.data[key] = value
        return True

    def delete(self, key: str) -> None:
        self.data.pop(key, None)


class BrokenRedis:
    def set(self, *args, **kwargs):
        raise redis.ConnectionError("down")

    def delete(self, *args, **kwargs):
        raise redis.ConnectionError("down")


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(token_once, "_client", fake)
    return fake


def test_a_token_id_is_claimed_once(store: FakeRedis) -> None:
    assert claim("a") is True
    assert claim("a") is False


def test_other_ids_are_independent(store: FakeRedis) -> None:
    assert claim("a") is True
    assert claim("b") is True


def test_a_confirmed_id_stays_used(store: FakeRedis) -> None:
    claim("a")
    confirm("a")
    assert claim("a") is False


def test_a_released_id_can_be_claimed_again(store: FakeRedis) -> None:
    claim("a")
    release("a")
    assert claim("a") is True


def test_redis_errors_fail_closed_with_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(token_once, "_client", BrokenRedis())
    with pytest.raises(ConfirmationStoreUnavailableError):
        claim("a")
    # Still refused: nothing was remembered in this process.
    with pytest.raises(ConfirmationStoreUnavailableError):
        claim("a")


def test_confirm_and_release_do_not_raise_when_redis_is_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(token_once, "_client", BrokenRedis())
    confirm("a")
    release("a")
