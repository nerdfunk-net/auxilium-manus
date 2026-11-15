import asyncio
import os
import stat
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from manus_agent.fping import FpingError, HostResult, parse_summary, run_fping

SUMMARY = textwrap.dedent(
    """\
    10.0.0.1   : xmt/rcv/%loss = 3/3/0%, min/avg/max = 0.40/0.50/0.61
    10.0.0.2   : xmt/rcv/%loss = 3/2/33%, min/avg/max = 1.0/2.5/4.0
    10.0.0.3   : xmt/rcv/%loss = 3/0/100%
    """
)


class ParseSummaryTests(unittest.TestCase):
    def test_reachable_lossy_and_silent_hosts(self) -> None:
        results = parse_summary(SUMMARY)
        assert results == [
            HostResult("10.0.0.1", True, 0.5, 0),
            HostResult("10.0.0.2", True, 2.5, 33),
            HostResult("10.0.0.3", False, None, 100),
        ]

    def test_lines_that_are_not_summaries_are_ignored(self) -> None:
        text = "ICMP Host Unreachable from 10.0.0.9 for ICMP Echo sent to 10.0.0.4\n" + SUMMARY
        assert [r.ip for r in parse_summary(text)] == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]

    def test_empty_output(self) -> None:
        assert parse_summary("") == []


def fake_fping(directory: Path, script: str) -> Path:
    path = directory / "fping"
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class RunFpingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_runs_with_the_hosts_on_stdin_and_parses_stderr(self) -> None:
        argv_log = self.dir / "argv"
        stdin_log = self.dir / "stdin"
        binary = fake_fping(
            self.dir,
            f'echo "$@" > {argv_log}\ncat > {stdin_log}\n'
            "echo '10.0.0.1 : xmt/rcv/%loss = 2/2/0%, min/avg/max = 1/2/3' >&2\n"
            "echo '10.0.0.2 : xmt/rcv/%loss = 2/0/100%' >&2\nexit 1\n",
        )
        results = await run_fping(
            ["10.0.0.1", "10.0.0.2"], count=2, timeout_ms=300, binary=str(binary)
        )
        assert [(r.ip, r.reachable) for r in results] == [("10.0.0.1", True), ("10.0.0.2", False)]
        argv = argv_log.read_text().split()
        assert argv[:3] == ["-4", "-q", "-c"] and "2" in argv and "300" in argv
        # -p: the period between probes of one host; fping's default of 1 s would make a short
        # list with count > 1 take count seconds whatever the timeout.
        assert argv[argv.index("-p") + 1] == "300"
        assert "-f" in argv and "-" in argv
        assert stdin_log.read_text().split() == ["10.0.0.1", "10.0.0.2"]

    async def test_a_real_error_exit_code_is_a_fixed_message(self) -> None:
        binary = fake_fping(self.dir, "cat >/dev/null\necho 'secret path /etc/x' >&2\nexit 4\n")
        with self.assertRaises(FpingError) as caught:
            await run_fping(["10.0.0.1"], count=1, timeout_ms=100, binary=str(binary))
        assert "/etc/x" not in str(caught.exception)

    async def test_missing_binary_is_a_clear_error(self) -> None:
        with self.assertRaises(FpingError) as caught:
            await run_fping(["10.0.0.1"], count=1, timeout_ms=100, binary="/nonexistent/fping")
        assert "fping" in str(caught.exception)

    async def test_cancelling_kills_the_process(self) -> None:
        pidfile = self.dir / "pid"
        binary = fake_fping(self.dir, f"echo $$ > {pidfile}\nexec sleep 30\n")
        task = asyncio.create_task(
            run_fping(["10.0.0.1"], count=1, timeout_ms=100, binary=str(binary))
        )
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            await asyncio.sleep(0.02)
        pid = int(pidfile.read_text())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            await asyncio.sleep(0.05)
        self.fail("fping process was left running")
