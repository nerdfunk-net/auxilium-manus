"""Run-segment-scoped pool of live Netmiko sessions.

One pool per execution segment (one ``StepRunner`` usage span — a phase-1
walk, a phase-4 post-join resume, or a fan-out child). Not shared across
Hatchet task invocations. All public methods are asyncio-safe; blocking
Netmiko I/O runs on the pool's private thread executor.

Invariant (see doc/DURABLE_SSH_SESSION.md §3.4): every ``op`` passed to
``run_on_device`` must leave the session in privileged-exec base state
(config mode always exited, no pending interactive prompts) before
returning, since a later call may reuse the same live session.

Login probes (``probe_login``) are a separate, disposable code path: they
never read, lock, or mutate an existing pooled entry, and the probe session
is never inserted into ``_sessions``. This lets a step confirm a fresh SSH
login without tearing down a pooled session a later rollback step may still
need — see doc/refactoring/FORCE_SSH_LOGIN.md.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TypeVar

from core.config import settings
from services.network.netmiko.connection import NetmikoDeviceSession

logger = logging.getLogger(__name__)

T = TypeVar("T")

# (host, device_type, credential_reference) — credential_reference (the vault
# name) is used instead of username/password so secrets never end up in the
# pool key or in logs; the resolved (username, password) lives only on the
# session object, same exposure class as today's per-call flow.
SessionKey = tuple[str, str, str]


@dataclass
class PooledSession:
    key: SessionKey
    session: NetmikoDeviceSession
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)
    ever_connected: bool = False


class DeviceSessionPool:
    """Acquire, reuse, and tear down live Netmiko sessions for one segment."""

    def __init__(self, *, max_workers: int = 10, enabled: bool = True) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="netmiko-pool"
        )
        self._enabled = enabled
        self._sessions: dict[SessionKey, PooledSession] = {}
        self._pool_lock = asyncio.Lock()
        self._created_total = 0
        self._reconnects = 0
        self._closed = False

    async def run_on_device(
        self,
        *,
        host: str,
        device_type: str,
        credential_reference: str,
        username: str,
        password: str,
        op: Callable[[NetmikoDeviceSession], T],
        debug: bool = False,
    ) -> T:
        """Acquire (or lazily create/reconnect) the session for this key, hold
        its per-session lock, run ``op(session)`` on the thread executor, and
        release. This is the only way to touch a session — it makes the
        not-thread-safe invariant structurally enforceable.

        When the pool is disabled, behaves exactly like the legacy per-call
        flow: a fresh session is connected, used once, and disconnected.
        """
        loop = asyncio.get_running_loop()

        if not self._enabled:
            session = NetmikoDeviceSession(
                host=host,
                device_type=device_type,
                username=username,
                password=password,
                keepalive=settings.netmiko_keepalive_seconds,
            )

            def _run_disposable() -> T:
                session.connect()
                try:
                    return op(session)
                finally:
                    session.disconnect()

            return await loop.run_in_executor(self._executor, _run_disposable)

        key: SessionKey = (host, device_type, credential_reference)
        entry = await self._get_or_create_entry(
            key, host=host, device_type=device_type, username=username, password=password
        )

        async with entry.lock:

            def _run() -> T:
                if not entry.session.is_alive():
                    if entry.ever_connected:
                        entry.session.disconnect()
                        self._reconnects += 1
                    entry.session.connect()
                    entry.ever_connected = True
                result = op(entry.session)
                if debug:
                    try:
                        if entry.session.check_config_mode():
                            logger.warning(
                                "Session left in config mode after op host=%s", host
                            )
                    except Exception:
                        logger.warning(
                            "check_config_mode failed host=%s", host, exc_info=True
                        )
                return result

            result = await loop.run_in_executor(self._executor, _run)
            entry.last_used = time.monotonic()
            return result

    async def probe_login(
        self,
        *,
        host: str,
        device_type: str,
        username: str,
        password: str,
    ) -> bool:
        """Open a disposable SSH session, confirm it is alive, disconnect.

        Does not read, lock, mutate, or replace any pooled session for this
        host — the probe session is never stored in ``_sessions``. Used by
        ``login-successful`` to guarantee a real new authentication even when
        a live pooled session already exists for the same key (see
        doc/DURABLE_SSH_SESSION.md §11 and doc/refactoring/FORCE_SSH_LOGIN.md).
        """
        loop = asyncio.get_running_loop()
        session = NetmikoDeviceSession(
            host=host,
            device_type=device_type,
            username=username,
            password=password,
            keepalive=settings.netmiko_keepalive_seconds,
        )

        def _probe() -> bool:
            try:
                session.connect()
                return session.is_alive()
            finally:
                session.disconnect()

        return await loop.run_in_executor(self._executor, _probe)

    async def _get_or_create_entry(
        self,
        key: SessionKey,
        *,
        host: str,
        device_type: str,
        username: str,
        password: str,
    ) -> PooledSession:
        async with self._pool_lock:
            entry = self._sessions.get(key)
            if entry is None:
                session = NetmikoDeviceSession(
                    host=host,
                    device_type=device_type,
                    username=username,
                    password=password,
                    keepalive=settings.netmiko_keepalive_seconds,
                )
                entry = PooledSession(key=key, session=session)
                self._sessions[key] = entry
                self._created_total += 1
            return entry

    async def suspend(self) -> None:
        """Disconnect every live session but keep the pool usable afterwards.

        Called before durable waits. Never raises — a disconnect failure is
        logged and the next acquire will reconnect anyway.
        """
        loop = asyncio.get_running_loop()
        for entry in list(self._sessions.values()):
            async with entry.lock:
                try:
                    await loop.run_in_executor(self._executor, entry.session.disconnect)
                except Exception:
                    logger.warning(
                        "Failed to disconnect session during suspend key=%s",
                        entry.key,
                        exc_info=True,
                    )

    async def close(self) -> None:
        """Disconnect everything and shut down the thread executor. Idempotent
        and never raises."""
        if self._closed:
            return
        self._closed = True
        await self.suspend()
        self._executor.shutdown(wait=False, cancel_futures=True)
        logger.info("DeviceSessionPool closed stats=%s", self.stats())

    def stats(self) -> dict[str, int]:
        return {
            "open": sum(1 for entry in self._sessions.values() if entry.session.is_alive()),
            "created_total": self._created_total,
            "reconnects": self._reconnects,
        }
