"""Live run events: who is running (context) and how to record what happened.

A step is a single ``running`` row until it ends, so connect retries and
per-device failures only reached the worker log. Executors need no changes:
``StepRunner`` binds a ``RunEventContext`` around each node, and
``DeviceSessionPool.run_on_device`` reads it *before* hopping to its thread
executor (contextvars do not propagate through ``run_in_executor``) and hands
an explicit callback to ``NetmikoDeviceSession.connect``.

Emission is synchronous, thread-safe (own short-lived session per event) and
strictly best-effort — recording an event must never fail a device run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# (kind, level, message) — the device name is bound by build_connect_event_callback.
ConnectEventCallback = Callable[[str, str, str], None]


@dataclass(frozen=True)
class RunEventContext:
    run_id: int
    node_id: str
    child_index: int | None = None


_current: ContextVar[RunEventContext | None] = ContextVar("run_event_context", default=None)


def current_run_event_context() -> RunEventContext | None:
    return _current.get()


@contextmanager
def bound_run_event_context(context: RunEventContext) -> Iterator[None]:
    token = _current.set(context)
    try:
        yield
    finally:
        _current.reset(token)


def emit_run_event(
    context: RunEventContext,
    *,
    kind: str,
    message: str,
    level: str = "info",
    device_name: str | None = None,
) -> None:
    """Persist one event. Safe to call from any thread; never raises."""
    # Lazy import: core.database pulls in the engine, and tests patch
    # core.database.SessionLocal.
    from core.database import SessionLocal
    from repositories.run_event_repository import RunEventRepository

    try:
        with SessionLocal() as db:
            RunEventRepository(db).add_event(
                run_id=context.run_id,
                step_node_id=context.node_id,
                child_index=context.child_index,
                kind=kind,
                message=message,
                level=level,
                device_name=device_name,
            )
    except Exception:
        logger.warning(
            "Failed to record run event run_id=%s node_id=%s kind=%s",
            context.run_id,
            context.node_id,
            kind,
            exc_info=True,
        )


def build_connect_event_callback(
    context: RunEventContext | None, *, device_name: str
) -> ConnectEventCallback | None:
    """Callback for ``NetmikoDeviceSession.connect``; None when nothing is bound."""
    if context is None:
        return None

    def _callback(kind: str, level: str, message: str) -> None:
        emit_run_event(context, kind=kind, message=message, level=level, device_name=device_name)

    return _callback
