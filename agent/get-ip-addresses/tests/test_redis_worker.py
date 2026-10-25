import asyncio
import json
import time
import unittest

from fakeredis import FakeAsyncRedis

from manus_agent.core import AgentCore
from manus_agent.redis_worker import RedisWorker, heartbeat_key, request_key, response_key
from tests.helpers import AGENT, make_config, make_registry, open_response, request_envelope

# What the ACL shown in the app's agent dialog grants; the worker must not need anything else.
ACL_COMMANDS = {"blpop", "rpush", "hset", "expire", "del", "ping"}


class RecordingRedis(FakeAsyncRedis):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commands: list[str] = []

    async def execute_command(self, *args, **options):
        self.commands.append(str(args[0]).lower())
        return await super().execute_command(*args, **options)


class FlakyRedis(RecordingRedis):
    """Raises ConnectionError on the first ``failures`` BLPOPs, like a restarting Redis."""

    def __init__(self, failures: int):
        super().__init__(decode_responses=True)
        self.failures = failures

    async def execute_command(self, *args, **options):
        # Only the worker's polling of the request queue fails, not the test's own reads.
        if str(args[0]).lower() == "blpop" and str(args[1]).endswith(":req") and self.failures > 0:
            self.failures -= 1
            raise ConnectionError("redis went away")
        return await super().execute_command(*args, **options)


class WorkerTestCase(unittest.IsolatedAsyncioTestCase):
    max_concurrency = 4

    def make_redis(self) -> RecordingRedis:
        return RecordingRedis(decode_responses=True)

    def make_handlers(self):
        return make_registry()

    async def asyncSetUp(self) -> None:
        self.redis = self.make_redis()
        self.addAsyncCleanup(self.redis.aclose)
        config = make_config(max_concurrency=self.max_concurrency, http_port=None)
        self.registry = self.make_handlers()
        # Requests are sealed with the real clock in these tests, so the core uses it too.
        self.core = AgentCore(config, self.registry, clock=time.time)
        self.worker = RedisWorker(
            self.core,
            config,
            self.registry,
            self.redis,
            heartbeat_interval=0.1,
            poll_timeout=0.1,
            retry_delay=0.05,
        )
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(self.worker.run(self.stop))
        self.addAsyncCleanup(self.shutdown)

    async def shutdown(self) -> None:
        self.stop.set()
        await asyncio.wait_for(self.task, 5)

    def envelope(self, handler="upper", command_id="cmd-1", **kwargs):
        return request_envelope(handler, command_id=command_id, now=int(time.time()), **kwargs)

    async def send(self, envelope) -> None:
        await self.redis.rpush(request_key(AGENT), json.dumps(envelope))

    async def answer(self, command_id="cmd-1", timeout=3.0):
        popped = await self.redis.blpop([response_key(AGENT, command_id)], timeout=timeout)
        return None if popped is None else json.loads(popped[1])


class WorkerTests(WorkerTestCase):
    async def test_answers_a_request_on_its_response_key(self) -> None:
        await self.send(self.envelope())
        payload = open_response(await self.answer(), now=int(time.time()))
        assert payload == {"status": "success", "output": {"v": "BERLIN"}}
        assert await self.redis.llen(request_key(AGENT)) == 0

    async def test_the_response_key_expires_if_nobody_collects_it(self) -> None:
        await self.send(self.envelope())
        for _ in range(50):
            if await self.redis.ttl(response_key(AGENT, "cmd-1")) > 0:
                break
            await asyncio.sleep(0.05)
        assert 0 < await self.redis.ttl(response_key(AGENT, "cmd-1")) <= 120

    async def test_handler_errors_come_back_as_answers(self) -> None:
        await self.send(self.envelope("boom"))
        assert open_response(await self.answer(), now=int(time.time()))["status"] == "error"

    async def test_bad_messages_get_no_answer_and_do_not_stop_the_worker(self) -> None:
        await self.send(self.envelope(command_id="bad", secret="z" * 40))
        await self.redis.rpush(request_key(AGENT), "not json")
        await self.redis.rpush(request_key(AGENT), json.dumps(["not", "an", "object"]))
        await self.send(self.envelope(command_id="good"))
        assert open_response(await self.answer("good"), command_id="good", now=int(time.time()))
        assert await self.redis.exists(response_key(AGENT, "bad")) == 0

    async def test_a_request_above_the_size_limit_is_dropped_unparsed(self) -> None:
        with self.assertLogs("manus_agent.redis_worker", "WARNING") as logs:
            await self.redis.rpush(request_key(AGENT), "[" + "0," * 1_048_576 + "0]")
            await self.send(self.envelope(command_id="after"))
            assert open_response(
                await self.answer("after"), command_id="after", now=int(time.time())
            )
        assert any("size limit" in line for line in logs.output)
        assert await self.redis.llen(request_key(AGENT)) == 0

    async def test_a_replayed_request_is_answered_once(self) -> None:
        envelope = self.envelope()
        await self.send(envelope)
        assert await self.answer() is not None
        await self.send(envelope)
        assert await self.answer(timeout=0.5) is None

    async def test_only_acl_permitted_commands_are_used(self) -> None:
        await self.send(self.envelope())
        await self.answer()
        await asyncio.sleep(0.3)  # at least one heartbeat
        self.stop.set()
        await self.task
        assert set(self.redis.commands) <= ACL_COMMANDS, set(self.redis.commands) - ACL_COMMANDS


class HeartbeatTests(WorkerTestCase):
    async def test_heartbeat_describes_the_agent(self) -> None:
        for _ in range(50):
            beat = await self.redis.hgetall(heartbeat_key(AGENT))
            if beat:
                break
            await asyncio.sleep(0.02)
        assert beat["status"] == "online"
        assert beat["version"]
        assert beat["handlers"].split(",") == self.registry.names()
        assert int(beat["last_heartbeat"]) > 0
        assert 0 < await self.redis.ttl(heartbeat_key(AGENT)) <= 90

    async def test_heartbeat_is_renewed(self) -> None:
        await asyncio.sleep(0.05)
        first = (await self.redis.hgetall(heartbeat_key(AGENT)))["last_heartbeat"]
        await self.redis.expire(heartbeat_key(AGENT), 1)
        await asyncio.sleep(0.4)
        assert await self.redis.ttl(heartbeat_key(AGENT)) > 1
        assert first

    async def test_shutdown_marks_the_agent_offline(self) -> None:
        await asyncio.sleep(0.15)
        assert await self.redis.exists(heartbeat_key(AGENT)) == 1
        self.stop.set()
        await self.task
        assert await self.redis.exists(heartbeat_key(AGENT)) == 0


class ConcurrencyTests(WorkerTestCase):
    max_concurrency = 2

    def make_handlers(self):
        self.release = asyncio.Event()
        self.started: list[int] = []

        async def gated(params: dict, inputs: dict) -> dict:
            self.started.append(1)
            await self.release.wait()
            return {}

        registry = make_registry()
        registry.register("gated", gated)
        return registry

    async def test_it_does_not_pull_more_than_it_can_run(self) -> None:
        for i in range(6):
            await self.send(self.envelope("gated", command_id=f"c{i}"))
        await asyncio.sleep(0.5)
        assert len(self.started) == 2
        assert await self.redis.llen(request_key(AGENT)) == 4  # left in the queue, not buffered
        self.release.set()
        for i in range(6):
            assert await self.answer(f"c{i}") is not None


class ReconnectTests(WorkerTestCase):
    def make_redis(self) -> RecordingRedis:
        return FlakyRedis(failures=3)

    async def test_it_recovers_when_redis_comes_back(self) -> None:
        await self.send(self.envelope())
        assert await self.answer() is not None


if __name__ == "__main__":
    unittest.main()
