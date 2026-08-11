import asyncio
import json

import pytest

from app.config import ShimSettings
from app.job_runner import JobRunner, JobTimeoutError

_DEVICES = [
    {"name": "sw1", "host": "10.0.0.1", "os": "iosxe", "username": "admin", "password": "admin"}
]


def _settings(**overrides) -> ShimSettings:
    defaults = dict(
        token="test-token",
        port=8100,
        max_concurrent_jobs=2,
        job_timeout_seconds=5,
        pyats_bin="pyats",
    )
    defaults.update(overrides)
    return ShimSettings(**defaults)


class _FakeProcess:
    def __init__(self, *, returncode=0, stderr=b"", result_writer=None):
        self.returncode = returncode
        self._stderr = stderr
        self._result_writer = result_writer
        self.pid = 12345

    async def communicate(self):
        if self._result_writer is not None:
            self._result_writer()
        return b"", self._stderr

    async def wait(self):
        return self.returncode


async def test_run_reads_result_file_written_by_job(monkeypatch):
    written_result = {"sw1": {"success": True, "error": None, "commands": {}}}

    async def fake_create_subprocess_exec(*args, **kwargs):
        result_file = kwargs["env"]["PYATS_SHIM_RESULT_FILE"]

        def _write_result():
            with open(result_file, "w") as handle:
                json.dump(written_result, handle)

        return _FakeProcess(result_writer=_write_result)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    runner = JobRunner(_settings())
    result = await runner.run(operation="execute", devices=_DEVICES, commands=["show version"])

    assert result == written_result


async def test_run_falls_back_to_synthetic_error_when_no_result_file(monkeypatch):
    async def fake_create_subprocess_exec(*args, **kwargs):
        return _FakeProcess(returncode=1, stderr=b"boom")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    runner = JobRunner(_settings())
    result = await runner.run(operation="execute", devices=_DEVICES, commands=["show version"])

    assert result["sw1"]["success"] is False
    assert "boom" in result["sw1"]["error"]


async def test_run_raises_job_timeout_error_and_kills_process_group(monkeypatch):
    killed = {}

    class _HangingProcess:
        pid = 12345

        async def communicate(self):
            await asyncio.sleep(10)
            return b"", b""

        async def wait(self):
            return 0

    async def fake_create_subprocess_exec(*args, **kwargs):
        return _HangingProcess()

    def fake_killpg(pgid, sig):
        killed["called"] = True

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr("app.job_runner.os.killpg", fake_killpg)
    monkeypatch.setattr("app.job_runner.os.getpgid", lambda pid: pid)

    runner = JobRunner(_settings(job_timeout_seconds=0.05))
    with pytest.raises(JobTimeoutError):
        await runner.run(operation="execute", devices=_DEVICES, commands=["show version"])

    assert killed.get("called") is True
