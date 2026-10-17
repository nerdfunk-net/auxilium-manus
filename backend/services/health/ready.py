from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from models.health import ReadyCheck, ReadyResponse

logger = logging.getLogger(__name__)

READINESS_TIMEOUT_SECONDS = 3.0

# Probes that hang (a black-holed Redis, an exhausted connection pool) keep their thread until the
# socket or pool timeout fires. A small dedicated executor keeps them from using up the threads
# that other work shares; when it is full the probe simply reports "unavailable".
_PROBE_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="readiness")


def build_ready_response(
    *,
    database_ok: bool,
    database_error: str | None,
    redis_ok: bool,
    redis_error: str | None,
    vault_ok: bool | None = None,
    vault_error: str | None = None,
) -> tuple[int, ReadyResponse]:
    """Map database/redis check results to an HTTP status and response body."""
    all_ok = database_ok and redis_ok
    return (
        200 if all_ok else 503,
        ReadyResponse(
            status="ok" if all_ok else "unavailable",
            database=ReadyCheck(ok=database_ok, error=database_error),
            redis=ReadyCheck(ok=redis_ok, error=redis_error),
            vault=None if vault_ok is None else ReadyCheck(ok=vault_ok, error=vault_error),
        ),
    )


async def _probe(name: str, check: Callable[[], None], timeout: float) -> str | None:
    """Run one blocking check off the event loop. ``None`` means healthy, otherwise the error."""
    loop = asyncio.get_running_loop()
    try:
        await asyncio.wait_for(loop.run_in_executor(_PROBE_EXECUTOR, check), timeout)
    except TimeoutError:
        logger.warning("Readiness check: %s did not answer within %.1f s", name, timeout)
        return "unavailable"
    except Exception:
        logger.exception("Readiness check: %s unreachable", name)
        return "unavailable"
    return None


async def check_readiness(
    *,
    ping_database: Callable[[], None],
    ping_redis: Callable[[], None],
    vault_status: Callable[[], bool | None],
    timeout: float = READINESS_TIMEOUT_SECONDS,
) -> tuple[int, ReadyResponse]:
    """Probe database and Redis concurrently, each with a deadline, and build the response.

    ``vault_status`` returns ``None`` when OpenBao is not enabled. It reads in-memory state, so it
    runs inline.
    """
    database_error, redis_error = await asyncio.gather(
        _probe("database", ping_database, timeout),
        _probe("redis", ping_redis, timeout),
    )
    vault_ok = vault_status()
    return build_ready_response(
        database_ok=database_error is None,
        database_error=database_error,
        redis_ok=redis_error is None,
        redis_error=redis_error,
        vault_ok=vault_ok,
        vault_error=None if vault_ok in (None, True) else "unavailable",
    )
