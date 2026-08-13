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
import time
from pathlib import Path
from typing import Any

import yaml

from app.config import ShimSettings
from app.log_markers import CONNECT_MARKER
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
        runinfo_dir.mkdir(parents=True, exist_ok=True)

        testbed_path.write_text(yaml.safe_dump(testbed, sort_keys=False))
        request_path.write_text(json.dumps({"operation": operation, "commands": commands}))

        env = {
            **os.environ,
            "PYATS_SHIM_REQUEST_FILE": str(request_path),
            "PYATS_SHIM_RESULT_FILE": str(result_path),
        }

        device_names = list(testbed["devices"])
        device_hosts = {
            name: dev["connections"]["cli"]["ip"] for name, dev in testbed["devices"].items()
        }
        logger.info(
            "launching pyats run job operation=%s devices=%s work_dir=%s timeout=%s",
            operation,
            device_hosts,
            work_dir,
            timeout,
        )
        started_at = time.monotonic()

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
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            logger.error(
                "pyats run job timed out after %.1fs devices=%s",
                time.monotonic() - started_at,
                device_names,
            )
            self._kill_process_group(proc)
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()
            raise JobTimeoutError(f"pyATS job did not complete within {timeout} seconds") from None

        elapsed = time.monotonic() - started_at
        self._log_connect_events(stdout, stderr)

        if result_path.exists():
            logger.info(
                "pyats run job finished exit_code=%s elapsed=%.1fs devices=%s",
                proc.returncode,
                elapsed,
                device_names,
            )
            return json.loads(result_path.read_text())

        # 20000 chars, not 4000: easypy's report footer alone (printed last) can
        # run past 4000 chars, which was silently pushing the actual exception
        # -- printed just *before* the footer -- out of a shorter tail window.
        stderr_tail = stderr.decode(errors="replace")[-20000:]
        stdout_tail = stdout.decode(errors="replace")[-20000:]
        logger.error(
            "pyATS job produced no result file (exit code %s, elapsed %.1fs) stdout=%r stderr=%r",
            proc.returncode,
            elapsed,
            stdout_tail,
            stderr_tail,
        )
        error = f"pyATS job produced no results (exit code {proc.returncode}): {stderr_tail or stdout_tail}"
        return {name: {"success": False, "error": error, "commands": {}} for name in testbed["devices"]}

    @staticmethod
    def _log_connect_events(stdout: bytes, stderr: bytes) -> None:
        """Forward only ``[pyats-connect]``-marked lines from the subprocess output.

        The rest of the subprocess's stdout/stderr can contain raw device
        command output (e.g. running-config) and must never be logged in
        full -- see the security notes in doc/PYATS_INTEGRATION.md.
        """
        for raw in (stdout, stderr):
            for line in raw.decode(errors="replace").splitlines():
                if CONNECT_MARKER in line:
                    logger.info("%s", line.strip())

    @staticmethod
    def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
