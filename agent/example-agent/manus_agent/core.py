"""Open a request, run the handler it names and seal the answer.

Transport-independent: the HTTP server and the Redis worker both hand a request envelope to
``AgentCore.handle`` and send back what it returns. Anything that fails authentication, is
expired or has been seen before raises ``RequestRejected`` (nothing is executed and the
transport decides how to refuse); everything after authentication, including a crashing
handler, becomes an ordinary sealed ``error`` answer that the app shows to the user.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from manus_agent.config import AgentConfig
from manus_agent.envelope import EnvelopeError, open_envelope, seal
from manus_agent.registry import HANDLER_NAME_PATTERN, HandlerRegistry

logger = logging.getLogger(__name__)

# A handler always gets at least this long, even for a request that is about to expire.
MIN_HANDLER_SECONDS = 1.0
# How long the app has to pick up an answer, counted from the moment it was produced (not from
# when the request arrived: a handler may run for minutes).
RESPONSE_TTL_SECONDS = 60
MAX_ERROR_MESSAGE_CHARS = 200


class RequestRejected(Exception):
    """The request was not executed. ``reason`` is unauthenticated, replay or malformed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _error(error_type: str, message: str = "") -> dict[str, Any]:
    return {
        "status": "error",
        "output": None,
        "error": {"type": error_type, "message": message[:MAX_ERROR_MESSAGE_CHARS]},
    }


class AgentCore:
    def __init__(
        self,
        config: AgentConfig,
        registry: HandlerRegistry,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._registry = registry
        self._clock = clock
        self._gate = asyncio.Semaphore(config.max_concurrency)
        # Plain-function handlers run here. The pool is as big as the gate, and a slot is only
        # given back when the thread returns, so threads can never outnumber max_concurrency.
        self._pool = ThreadPoolExecutor(
            max_workers=config.max_concurrency, thread_name_prefix="manus-handler"
        )
        # command_id -> expiry. A message is only valid until its ``exp``, so remembering the
        # id until then is enough to refuse a replay.
        self._seen: dict[str, int] = {}

    async def handle(self, envelope: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(envelope, dict):
            raise RequestRejected("malformed")
        now = int(self._clock())
        try:
            opened = open_envelope(
                envelope,
                secret=self._config.secret,
                expected_agent_id=self._config.agent_id,
                expected_direction="request",
                now=now,
            )
        except EnvelopeError as exc:
            # Authentication comes first: only a holder of the secret can burn a command id.
            logger.warning("rejected a message: %s", exc)
            raise RequestRejected("unauthenticated") from exc

        self._forget_expired(now)
        if opened.command_id in self._seen:
            logger.warning("rejected a replayed command %s", opened.command_id)
            raise RequestRejected("replay")
        self._seen[opened.command_id] = opened.expires_at

        answer = await self._execute(opened.payload, remaining=opened.expires_at - now)
        return seal(
            answer,
            secret=self._config.secret,
            agent_id=self._config.agent_id,
            command_id=opened.command_id,
            direction="response",
            ttl_seconds=RESPONSE_TTL_SECONDS,
            # Read the clock again: the handler may have run for a long time.
            now=int(self._clock()),
        )

    def close(self) -> None:
        """Stop accepting handler work. A thread stuck in a handler cannot be interrupted."""
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _forget_expired(self, now: int) -> None:
        for command_id in [c for c, exp in self._seen.items() if exp < now]:
            del self._seen[command_id]

    async def _execute(self, payload: dict[str, Any], *, remaining: int) -> dict[str, Any]:
        name, params, inputs = (
            payload.get("handler"),
            payload.get("params"),
            payload.get("inputs"),
        )
        if (
            not isinstance(name, str)
            or not HANDLER_NAME_PATTERN.fullmatch(name)
            or not isinstance(params, dict)
            or not isinstance(inputs, dict)
        ):
            return _error("InvalidRequest", "handler, params and inputs are required")
        func = self._registry.get(name)
        if func is None:
            return _error("UnknownHandler", f"no handler named {name!r}")

        loop = asyncio.get_running_loop()
        started = loop.time()
        budget = max(MIN_HANDLER_SECONDS, remaining)
        try:
            await asyncio.wait_for(self._gate.acquire(), timeout=budget)
        except TimeoutError:
            return _error("HandlerTimeout", "agent is busy: no free handler slot in time")
        try:
            left = max(MIN_HANDLER_SECONDS, budget - (loop.time() - started))
            result = await self._run(func, params, inputs, left)
        except TimeoutError:
            return _error("HandlerTimeout", f"{name} did not finish in time")
        except Exception as exc:
            logger.warning("handler %s failed: %s", name, type(exc).__name__, exc_info=True)
            return _error(type(exc).__name__, str(exc))

        if not isinstance(result, dict):
            return _error("InvalidOutput", "a handler must return a JSON object")
        try:
            size = len(json.dumps(result, allow_nan=False).encode("utf-8"))
        except (TypeError, ValueError, RecursionError):
            return _error("InvalidOutput", "the returned object is not valid JSON")
        if size > self._config.max_response_bytes:
            return _error(
                "InvalidOutput",
                f"the answer is {size} bytes, above the limit of {self._config.max_response_bytes}",
            )
        return {"status": "success", "output": result}

    async def _run(
        self,
        func: Callable[..., Any],
        params: dict[str, Any],
        inputs: dict[str, Any],
        timeout: float,  # noqa: ASYNC109 - a budget for one handler, not an asyncio.timeout() scope
    ) -> Any:
        """Run one handler and give its slot back exactly when it is really finished."""
        if inspect.iscoroutinefunction(func):
            try:
                return await asyncio.wait_for(func(params, inputs), timeout=timeout)
            finally:
                self._gate.release()
        # A plain function may block (network, files), so it runs in a thread. A timeout cannot
        # stop a thread: the slot stays taken until the function returns, so a stuck handler
        # costs one slot instead of leaking a new thread on every request.
        future = asyncio.get_running_loop().run_in_executor(self._pool, func, params, inputs)
        future.add_done_callback(self._thread_finished)
        # asyncio.wait, not wait_for/shield: on timeout it leaves the future alone (the thread
        # cannot be stopped) and nothing is logged when that thread fails later.
        done, _ = await asyncio.wait({future}, timeout=timeout)
        if not done:
            raise TimeoutError
        result = future.result()
        return await result if inspect.isawaitable(result) else result

    def _thread_finished(self, future: asyncio.Future[Any]) -> None:
        self._gate.release()
        if not future.cancelled():
            future.exception()  # mark it retrieved: nobody may be waiting any more
