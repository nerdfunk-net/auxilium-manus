"""O2-03: the readiness probe must never block the event loop or wait on a hung dependency."""

from __future__ import annotations

import asyncio
import time

from services.health.ready import check_readiness


def _ok() -> None:
    return None


def _boom() -> None:
    raise ConnectionError("refused")


def _hang(seconds: float):
    def probe() -> None:
        time.sleep(seconds)

    return probe


def _run(**kwargs):
    kwargs.setdefault("ping_database", _ok)
    kwargs.setdefault("ping_redis", _ok)
    kwargs.setdefault("vault_status", lambda: None)
    kwargs.setdefault("timeout", 1.0)
    return asyncio.run(check_readiness(**kwargs))


def test_everything_reachable_is_200() -> None:
    status_code, body = _run()
    assert status_code == 200
    assert body.status == "ok"
    assert body.vault is None


def test_an_unreachable_redis_is_unavailable_never_unconfigured() -> None:
    status_code, body = _run(ping_redis=_boom)
    assert status_code == 503
    assert body.redis.ok is False
    assert body.redis.error == "unavailable"
    assert body.database.ok is True


def test_an_unreachable_database_is_unavailable() -> None:
    status_code, body = _run(ping_database=_boom)
    assert status_code == 503
    assert body.database.error == "unavailable"


def test_a_hanging_redis_is_cut_off_at_the_timeout() -> None:
    started = time.monotonic()
    status_code, body = _run(ping_redis=_hang(1.5), timeout=0.2)
    elapsed = time.monotonic() - started
    assert status_code == 503
    assert body.redis.error == "unavailable"
    assert elapsed < 1.0


def test_a_hanging_database_is_cut_off_at_the_timeout() -> None:
    started = time.monotonic()
    status_code, body = _run(ping_database=_hang(1.5), timeout=0.2)
    assert status_code == 503
    assert body.database.error == "unavailable"
    assert time.monotonic() - started < 1.0


def test_the_event_loop_keeps_running_while_a_probe_blocks() -> None:
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    async def scenario() -> None:
        task = asyncio.create_task(ticker())
        await check_readiness(
            ping_database=_ok,
            ping_redis=_hang(0.5),
            vault_status=lambda: None,
            timeout=1.0,
        )
        task.cancel()

    asyncio.run(scenario())
    # A blocked loop would have counted (almost) nothing during the 0.5 s probe.
    assert ticks >= 10


def test_vault_down_is_reported_but_not_blocking() -> None:
    status_code, body = _run(vault_status=lambda: False)
    assert status_code == 200
    assert body.vault is not None and body.vault.ok is False
    assert body.vault.error == "unavailable"


def test_probes_run_concurrently() -> None:
    started = time.monotonic()
    _run(ping_database=_hang(0.4), ping_redis=_hang(0.4), timeout=2.0)
    assert time.monotonic() - started < 0.7
