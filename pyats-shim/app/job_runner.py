"""Runs one pyATS job per shim request and returns its results.

Each request gets its own temp dir with a generated testbed.yaml and
request.json; the job is launched via `pyats run job` as a subprocess (with
`--no-archive --runinfo-dir <workdir>/runinfo` so pyATS never writes outside
the per-request temp dir), and the AEtest script writes its results to a
result.json the runner reads back. The subprocess is wrapped in an overall
timeout that kills the whole process group on expiry — this is the actual
safety net against a hung device connection, not any per-device Unicon
timeout (verify/tune Unicon's own `connection_timeout` against real devices
during hardening; until then, one unreachable device can hold up the whole
batch until this timeout fires).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import tempfile
from pathlib import Path
from typing import Any

import yaml

from app.config import ShimSettings
from app.testbed_builder import build_testbed_dict

logger = logging.getLogger(__name__)

_JOB_SCRIPT = Path(__file__).parent / "job_scripts" / "generic_job.py"


class JobTimeoutError(Exception):
    """Raised when a pyATS job does not complete within the configured timeout."""


class JobRunner:
    def __init__(self, settings: ShimSettings) -> None:
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

    async def run(
        self,
        *,
        operation: str,
        devices: list[dict[str, Any]],
        commands: list[str],
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        timeout = timeout_seconds or self._settings.job_timeout_seconds
        testbed = build_testbed_dict(devices)

        async with self._semaphore:
            work_dir = Path(tempfile.mkdtemp(prefix="pyats-job-"))
            try:
                return await self._run_in_workdir(work_dir, testbed, operation, commands, timeout)
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

    async def _run_in_workdir(
        self,
        work_dir: Path,
        testbed: dict[str, Any],
        operation: str,
        commands: list[str],
        timeout: float,
    ) -> dict[str, Any]:
        testbed_path = work_dir / "testbed.yaml"
        request_path = work_dir / "request.json"
        result_path = work_dir / "result.json"
        runinfo_dir = work_dir / "runinfo"

        testbed_path.write_text(yaml.safe_dump(testbed, sort_keys=False))
        request_path.write_text(json.dumps({"operation": operation, "commands": commands}))

        env = {
            **os.environ,
            "PYATS_SHIM_REQUEST_FILE": str(request_path),
            "PYATS_SHIM_RESULT_FILE": str(result_path),
        }

        proc = await asyncio.create_subprocess_exec(
            self._settings.pyats_bin,
            "run",
            "job",
            str(_JOB_SCRIPT),
            "--testbed-file",
            str(testbed_path),
            "--no-mail",
            "--no-archive",
            "--runinfo-dir",
            str(runinfo_dir),
            cwd=str(work_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        try:
            _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            self._kill_process_group(proc)
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()
            raise JobTimeoutError(f"pyATS job did not complete within {timeout} seconds") from None

        if result_path.exists():
            return json.loads(result_path.read_text())

        stderr_tail = stderr.decode(errors="replace")[-4000:]
        logger.error(
            "pyATS job produced no result file (exit code %s): %s", proc.returncode, stderr_tail
        )
        error = f"pyATS job produced no results (exit code {proc.returncode}): {stderr_tail}"
        return {name: {"success": False, "error": error, "commands": {}} for name in testbed["devices"]}

    @staticmethod
    def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
