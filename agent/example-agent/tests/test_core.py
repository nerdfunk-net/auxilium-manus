import asyncio
import threading
import unittest
from unittest.mock import patch

from manus_agent.core import AgentCore, RequestRejected
from manus_agent.envelope import seal
from tests.helpers import (
    AGENT,
    NOW,
    SECRET,
    make_config,
    make_registry,
    open_response,
    request_envelope,
)


def make_core(**config_overrides) -> AgentCore:
    return AgentCore(make_config(**config_overrides), make_registry(), clock=lambda: NOW)


class SuccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_runs_a_sync_handler_and_seals_the_answer(self) -> None:
        response = await make_core().handle(request_envelope("upper"))
        assert open_response(response) == {"status": "success", "output": {"v": "BERLIN"}}

    async def test_runs_an_async_handler(self) -> None:
        response = await make_core().handle(
            request_envelope("slow", params={"seconds": 0}, ttl=30)
        )
        assert open_response(response)["output"] == {"done": True}

    async def test_echo_returns_its_inputs(self) -> None:
        response = await make_core().handle(request_envelope("echo", inputs={"nonce": "abc"}))
        assert open_response(response)["output"] == {"nonce": "abc"}

    async def test_the_answer_is_bound_to_the_command(self) -> None:
        response = await make_core().handle(request_envelope(command_id="cmd-9"))
        assert response["command_id"] == "cmd-9"
        assert response["direction"] == "response"
        assert open_response(response, command_id="cmd-9")["status"] == "success"


class HandlerErrorTests(unittest.IsolatedAsyncioTestCase):
    async def _error(self, **kwargs) -> dict:
        payload = open_response(await make_core().handle(request_envelope(**kwargs)))
        assert payload["status"] == "error"
        assert payload.get("output") is None
        return payload["error"]

    async def test_unknown_handler(self) -> None:
        error = await self._error(handler="nope")
        assert error["type"] == "UnknownHandler"

    async def test_exception_is_reported_by_class_and_message(self) -> None:
        error = await self._error(handler="boom")
        assert error["type"] == "KeyError"
        assert "site" in error["message"]

    async def test_long_messages_are_truncated(self) -> None:
        core = make_core()

        def verbose(params: dict, inputs: dict) -> dict:
            raise ValueError("x" * 5000)

        core._registry.register("verbose", verbose)
        payload = open_response(await core.handle(request_envelope("verbose")))
        assert len(payload["error"]["message"]) <= 200

    async def test_output_must_be_a_json_object(self) -> None:
        assert (await self._error(handler="not_a_dict"))["type"] == "InvalidOutput"
        assert (await self._error(handler="not_json"))["type"] == "InvalidOutput"

    async def test_malformed_requests_get_an_error_answer(self) -> None:
        for payload in (
            {"handler": 5, "params": {}, "inputs": {}},
            {"handler": "upper", "params": [], "inputs": {}},
            {"handler": "upper", "params": {}, "inputs": "text"},
            {"params": {}, "inputs": {}},
            {"handler": "../x", "params": {}, "inputs": {}},
        ):
            error = await self._error(payload=payload)
            assert error["type"] == "InvalidRequest", payload

    async def test_a_handler_that_outlives_the_request_times_out(self) -> None:
        core = make_core()
        envelope = request_envelope("slow", params={"seconds": 30}, ttl=1)
        with patch("manus_agent.core.MIN_HANDLER_SECONDS", 0.05):
            payload = open_response(await core.handle(envelope))
        assert payload["error"]["type"] == "HandlerTimeout"


class RejectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_secret_is_unauthenticated(self) -> None:
        envelope = request_envelope(secret="z" * 40)
        with self.assertRaises(RequestRejected) as ctx:
            await make_core().handle(envelope)
        assert ctx.exception.reason == "unauthenticated"

    async def test_tampered_message_is_unauthenticated(self) -> None:
        envelope = request_envelope()
        envelope["command_id"] = "other"
        with self.assertRaises(RequestRejected) as ctx:
            await make_core().handle(envelope)
        assert ctx.exception.reason == "unauthenticated"

    async def test_message_for_another_agent_is_refused(self) -> None:
        envelope = request_envelope(agent_id="other-agent")
        with self.assertRaises(RequestRejected):
            await make_core().handle(envelope)

    async def test_a_response_cannot_be_sent_as_a_request(self) -> None:
        envelope = seal(
            {"handler": "echo", "params": {}, "inputs": {}},
            secret=SECRET, agent_id=AGENT, command_id="c", direction="response",
            ttl_seconds=30, now=NOW,
        )
        with self.assertRaises(RequestRejected):
            await make_core().handle(envelope)

    async def test_expired_request_is_refused(self) -> None:
        envelope = request_envelope(now=NOW - 100, ttl=30)
        with self.assertRaises(RequestRejected) as ctx:
            await make_core().handle(envelope)
        assert ctx.exception.reason == "unauthenticated"

    async def test_non_objects_are_malformed(self) -> None:
        for bad in ("text", 5, None, ["x"]):
            with self.assertRaises(RequestRejected):
                await make_core().handle(bad)  # type: ignore[arg-type]

    async def test_a_command_id_is_accepted_only_once(self) -> None:
        core = make_core()
        envelope = request_envelope()
        await core.handle(envelope)
        with self.assertRaises(RequestRejected) as ctx:
            await core.handle(envelope)
        assert ctx.exception.reason == "replay"

    async def test_the_replay_cache_forgets_expired_commands(self) -> None:
        now = {"t": NOW}
        core = AgentCore(make_config(), make_registry(), clock=lambda: now["t"])
        await core.handle(request_envelope(command_id="old", ttl=10))
        assert "old" in core._seen
        now["t"] = NOW + 5
        await core.handle(request_envelope(command_id="new", now=NOW + 5, ttl=10))
        now["t"] = NOW + 11
        await core.handle(request_envelope(command_id="newer", now=NOW + 11, ttl=10))
        assert "old" not in core._seen

    async def test_a_rejected_message_does_not_burn_its_command_id(self) -> None:
        core = make_core()
        with self.assertRaises(RequestRejected):
            await core.handle(request_envelope(secret="z" * 40))
        # the same command id with the right secret is still fine
        await core.handle(request_envelope())


class LateAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_answer_is_sealed_when_produced_not_when_the_request_arrived(self) -> None:
        # A handler that takes 120 s (the step allows up to 600) used to return a response that
        # was already expired: exp was "handler start + 60 s".
        now = {"t": NOW}
        core = AgentCore(make_config(), make_registry(), clock=lambda: now["t"])

        async def long_running(params: dict, inputs: dict) -> dict:
            now["t"] += 120
            return {"done": True}

        core._registry.register("long_running", long_running)
        response = await core.handle(request_envelope("long_running", ttl=600))
        # opens fine at the time it was produced, with the full delivery window left
        payload = open_response(response, now=NOW + 120)
        assert payload["output"] == {"done": True}
        assert response["exp"] - response["iat"] == 60
        assert response["iat"] == NOW + 120


class AbandonedHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_timed_out_sync_handler_keeps_its_slot_until_the_thread_returns(self) -> None:
        release = threading.Event()
        started: list[int] = []

        def stuck(params: dict, inputs: dict) -> dict:
            started.append(1)
            release.wait(10)
            return {"finally": True}

        core = make_core(max_concurrency=1)
        core._registry.register("stuck", stuck)
        self.addCleanup(release.set)
        self.addCleanup(core.close)

        with patch("manus_agent.core.MIN_HANDLER_SECONDS", 0.1):
            first = open_response(
                await core.handle(request_envelope("stuck", command_id="a", ttl=1)), command_id="a"
            )
            assert first["error"]["type"] == "HandlerTimeout"
            # The thread is still blocked. A second call must not start another thread...
            second = open_response(
                await core.handle(request_envelope("stuck", command_id="b", ttl=1)), command_id="b"
            )
        assert second["error"]["type"] == "HandlerTimeout"
        assert "busy" in second["error"]["message"]
        assert len(started) == 1

        # ...and once the stuck thread returns, the slot is free again.
        release.set()
        await asyncio.sleep(0.2)
        third = open_response(
            await core.handle(request_envelope("upper", command_id="c")), command_id="c"
        )
        assert third["status"] == "success"

    async def test_time_spent_waiting_for_a_slot_counts_against_the_request(self) -> None:
        core = make_core(max_concurrency=1)
        gate_holder = asyncio.create_task(
            core.handle(request_envelope("slow", params={"seconds": 3.0}, command_id="a", ttl=30))
        )
        await asyncio.sleep(0.05)
        with patch("manus_agent.core.MIN_HANDLER_SECONDS", 0.1):
            waiting = open_response(
                await core.handle(request_envelope("upper", command_id="b", ttl=1)), command_id="b"
            )
        assert waiting["error"]["type"] == "HandlerTimeout"
        gate_holder.cancel()

    async def test_an_abandoned_threads_late_exception_is_not_left_unretrieved(self) -> None:
        release = threading.Event()

        def stuck_then_fail(params: dict, inputs: dict) -> dict:
            release.wait(10)
            raise RuntimeError("late")

        core = make_core(max_concurrency=1)
        core._registry.register("late_fail", stuck_then_fail)
        self.addCleanup(core.close)
        with patch("manus_agent.core.MIN_HANDLER_SECONDS", 0.1):
            await core.handle(request_envelope("late_fail", ttl=1))
        loop = asyncio.get_running_loop()
        problems: list[dict] = []
        loop.set_exception_handler(lambda _loop, context: problems.append(context))
        release.set()
        await asyncio.sleep(0.3)
        import gc

        gc.collect()
        assert problems == []


class ResponseSizeTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_answer_above_the_limit_becomes_an_error(self) -> None:
        core = make_core(max_response_bytes=2048)
        core._registry.register("big", lambda p, i: {"blob": "x" * 5000})
        payload = open_response(await core.handle(request_envelope("big")))
        assert payload["status"] == "error"
        assert payload["error"]["type"] == "InvalidOutput"
        assert "limit" in payload["error"]["message"]

    async def test_an_answer_within_the_limit_passes(self) -> None:
        core = make_core(max_response_bytes=2048)
        payload = open_response(await core.handle(request_envelope("upper")))
        assert payload["status"] == "success"


class ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_handlers_run_at_most_max_concurrency_at_a_time(self) -> None:
        running = {"now": 0, "max": 0}

        async def tracked(params: dict, inputs: dict) -> dict:
            running["now"] += 1
            running["max"] = max(running["max"], running["now"])
            await asyncio.sleep(0.02)
            running["now"] -= 1
            return {}

        core = make_core(max_concurrency=2)
        core._registry.register("tracked", tracked)
        await asyncio.gather(
            *[core.handle(request_envelope("tracked", command_id=f"c{i}")) for i in range(8)]
        )
        assert running["max"] == 2

    async def test_a_blocking_sync_handler_does_not_stall_the_loop(self) -> None:
        import time

        core = make_core()
        core._registry.register("blocking", lambda p, i: (time.sleep(0.2), {})[1])
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        await core.handle(request_envelope("blocking"))
        task.cancel()
        assert ticks >= 5


if __name__ == "__main__":
    unittest.main()
