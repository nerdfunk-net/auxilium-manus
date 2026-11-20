"""``async_scope`` must not leak a lease when the awaiting task is cancelled mid-acquire."""

from __future__ import annotations

import asyncio
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

from services.git.tree_scope import async_scope


class _Probe:
    def __init__(self) -> None:
        self.entering = threading.Event()
        self.may_enter = threading.Event()
        self.released = threading.Event()

    @contextmanager
    def lock(self) -> Iterator[str]:
        self.entering.set()
        self.may_enter.wait(5)  # stands in for polling a lock another run holds
        try:
            yield "held"
        finally:
            self.released.set()


class AsyncScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_normal_use_enters_and_exits(self) -> None:
        probe = _Probe()
        probe.may_enter.set()
        async with async_scope(probe.lock()) as value:
            self.assertEqual(value, "held")
            self.assertFalse(probe.released.is_set())
        self.assertTrue(probe.released.is_set())

    async def test_body_error_still_releases(self) -> None:
        probe = _Probe()
        probe.may_enter.set()
        with self.assertRaises(RuntimeError):
            async with async_scope(probe.lock()):
                raise RuntimeError("boom")
        self.assertTrue(probe.released.is_set())

    async def test_cancel_while_acquiring_releases_the_lock_once_it_is_taken(self) -> None:
        probe = _Probe()
        # Keep the context manager alive: a dropped @contextmanager generator runs its ``finally``
        # when it is garbage-collected, which would hide a missing explicit release.
        cm = probe.lock()

        async def use() -> None:
            async with async_scope(cm):
                self.fail("the body must not run after a cancel")  # pragma: no cover

        task = asyncio.create_task(use())
        await asyncio.to_thread(probe.entering.wait, 5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(probe.released.is_set())  # still acquiring: nothing to release yet

        probe.may_enter.set()  # the worker thread now gets the lock...
        released = await asyncio.to_thread(probe.released.wait, 5)
        self.assertTrue(released, "the lock taken after the cancel was never released")


class LateReleaseFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_failing_late_release_is_logged(self) -> None:
        entering = threading.Event()
        may_enter = threading.Event()
        exit_called = threading.Event()

        class _Broken:
            def __enter__(self) -> str:
                entering.set()
                may_enter.wait(5)
                return "held"

            def __exit__(self, *exc: object) -> None:
                exit_called.set()
                raise RuntimeError("redis went away")

        async def use() -> None:
            async with async_scope(_Broken()):
                self.fail("the body must not run after a cancel")  # pragma: no cover

        task = asyncio.create_task(use())
        await asyncio.to_thread(entering.wait, 5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with self.assertLogs("services.git.tree_scope", level="ERROR") as logs:
            may_enter.set()
            self.assertTrue(await asyncio.to_thread(exit_called.wait, 5))
            for t in threading.enumerate():
                if t.name == "git-scope-release":
                    await asyncio.to_thread(t.join, 5)
        self.assertTrue(any("releasing" in r.getMessage() for r in logs.records), logs.output)

    async def test_the_release_thread_is_not_a_daemon(self) -> None:
        started: list[threading.Thread] = []
        real_start = threading.Thread.start

        def spy(self: threading.Thread) -> None:
            started.append(self)
            real_start(self)

        entering = threading.Event()
        may_enter = threading.Event()

        class _Cm:
            def __enter__(self) -> str:
                entering.set()
                may_enter.wait(5)
                return "held"

            def __exit__(self, *exc: object) -> None:
                return None

        async def use() -> None:
            async with async_scope(_Cm()):
                pass  # pragma: no cover

        task = asyncio.create_task(use())
        await asyncio.to_thread(entering.wait, 5)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        with patch.object(threading.Thread, "start", spy):
            may_enter.set()
            for _ in range(100):
                if any(t.name == "git-scope-release" for t in started):
                    break
                await asyncio.sleep(0.05)
        release = [t for t in started if t.name == "git-scope-release"]
        self.assertTrue(release)
        self.assertFalse(release[0].daemon)


if __name__ == "__main__":
    unittest.main()
