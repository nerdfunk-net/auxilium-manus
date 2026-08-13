from __future__ import annotations

from models.health import ReadyCheck, ReadyResponse


def build_ready_response(
    *,
    database_ok: bool,
    database_error: str | None,
    redis_ok: bool,
    redis_error: str | None,
) -> tuple[int, ReadyResponse]:
    """Map database/redis check results to an HTTP status and response body."""
    all_ok = database_ok and redis_ok
    return (
        200 if all_ok else 503,
        ReadyResponse(
            status="ok" if all_ok else "unavailable",
            database=ReadyCheck(ok=database_ok, error=database_error),
            redis=ReadyCheck(ok=redis_ok, error=redis_error),
        ),
    )
