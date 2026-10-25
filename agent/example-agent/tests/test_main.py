import asyncio
import socket
import textwrap
import unittest
from pathlib import Path

import aiohttp
from fakeredis import FakeAsyncRedis

from manus_agent.main import build_registry, main, serve
from manus_agent.redis_worker import heartbeat_key
from tests.helpers import AGENT, SECRET, make_config

HANDLERS = Path(__file__).resolve().parents[1] / "handlers"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def write_handler(directory: Path, name: str = "mine.py") -> None:
    (directory / name).write_text(
        textwrap.dedent(
            """
            from manus_agent.registry import handler

            @handler("mine")
            def mine(params, inputs):
                return {"ok": True}
            """
        )
    )


class BuildRegistryTests(unittest.TestCase):
    def test_builtin_echo_plus_the_handlers_directory(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            write_handler(Path(tmp))
            registry = build_registry(make_config(handlers_dir=Path(tmp)))
        assert registry.names() == ["echo", "mine"]

    def test_the_shipped_example_handlers_load(self) -> None:
        registry = build_registry(make_config(handlers_dir=HANDLERS))
        assert "resolve_location" in registry.names()


class ServeTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_transport_serves_until_stopped(self) -> None:
        port = free_port()
        config = make_config(http_port=port)
        registry = build_registry(make_config(handlers_dir=HANDLERS))
        stop = asyncio.Event()
        task = asyncio.create_task(serve(config, registry, stop))
        try:
            async with aiohttp.ClientSession() as session:
                for _ in range(50):
                    try:
                        async with session.get(f"http://127.0.0.1:{port}/healthz") as response:
                            assert response.status == 200
                            break
                    except aiohttp.ClientConnectionError:
                        await asyncio.sleep(0.05)
                else:
                    raise AssertionError("server did not start")
        finally:
            stop.set()
            await asyncio.wait_for(task, 5)

    async def test_redis_transport_publishes_a_heartbeat_and_removes_it_on_stop(self) -> None:
        fake = FakeAsyncRedis(decode_responses=True)
        config = make_config(http_port=None, redis_url="redis://localhost")
        stop = asyncio.Event()
        task = asyncio.create_task(
            serve(config, build_registry(make_config(handlers_dir=HANDLERS)), stop,
                  redis_factory=lambda url: fake)
        )
        for _ in range(100):
            if await fake.exists(heartbeat_key(AGENT)):
                break
            await asyncio.sleep(0.02)
        beat = await fake.hgetall(heartbeat_key(AGENT))
        assert "resolve_location" in beat["handlers"]
        stop.set()
        await asyncio.wait_for(task, 5)
        assert await fake.exists(heartbeat_key(AGENT)) == 0


class SupervisionTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_dead_redis_worker_stops_the_agent_and_releases_http(self) -> None:
        class ExplodingRedis(FakeAsyncRedis):
            async def execute_command(self, *args, **options):
                if str(args[0]).lower() == "blpop":
                    raise RuntimeError("worker bug")
                return await super().execute_command(*args, **options)

        port = free_port()
        config = make_config(http_port=port, redis_url="redis://fake")
        registry = build_registry(make_config(handlers_dir=HANDLERS))
        stop = asyncio.Event()
        with self.assertRaises(RuntimeError):
            await asyncio.wait_for(
                serve(
                    config,
                    registry,
                    stop,
                    redis_factory=lambda url: ExplodingRedis(decode_responses=True),
                ),
                timeout=5,
            )
        # the HTTP side was cleaned up too: the port is free again
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", port))


class MainTests(unittest.TestCase):
    def test_bad_configuration_exits_2_without_printing_the_secret(self) -> None:
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = main(env={"MANUS_AGENT_ID": "geo", "MANUS_AGENT_SECRET": "short-secret-value"})
        assert code == 2
        assert "short-secret-value" not in buffer.getvalue()
        assert "MANUS_AGENT_" in buffer.getvalue()

    def test_a_crashing_agent_exits_1_so_the_supervisor_restarts_it(self) -> None:
        import contextlib
        import io
        from unittest.mock import patch

        env = {
            "MANUS_AGENT_ID": "geo",
            "MANUS_AGENT_SECRET": SECRET,
            "MANUS_AGENT_HTTP_PORT": "8080",
            "MANUS_AGENT_HANDLERS_DIR": str(HANDLERS),
        }
        with (
            patch("manus_agent.main._run", side_effect=RuntimeError("boom")),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            assert main(env=env) == 1

    def test_a_broken_handlers_directory_exits_3(self) -> None:
        import contextlib
        import io
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "broken.py").write_text("raise RuntimeError('boom')\n")
            env = {
                "MANUS_AGENT_ID": "geo",
                "MANUS_AGENT_SECRET": SECRET,
                "MANUS_AGENT_HTTP_PORT": "8080",
                "MANUS_AGENT_HANDLERS_DIR": tmp,
            }
            with contextlib.redirect_stderr(io.StringIO()):
                assert main(env=env) == 3


if __name__ == "__main__":
    unittest.main()
