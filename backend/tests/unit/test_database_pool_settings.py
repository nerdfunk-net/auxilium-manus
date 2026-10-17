"""The database pool is configured from the environment (C10-02)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _pool(env: dict[str, str]) -> tuple[int, int, float]:
    backend = Path(__file__).resolve().parents[2]
    clean = {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "ENV",
            "SECRET_KEY",
            "KDF_ITERATIONS",
            "DATABASE_POOL_SIZE",
            "DATABASE_MAX_OVERFLOW",
            "DATABASE_POOL_TIMEOUT",
            "MANUS_PROCESS_ROLE",
        }
    }
    clean.update({"ENV": "development", "HOME": str(backend), "MANUS_ENV_FILE": os.devnull, **env})
    code = (
        "from core.database import engine; p = engine.pool; "
        "print(p.size(), p._max_overflow, p._timeout)"
    )
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", code],
        cwd=backend,
        env=clean,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    size, overflow, timeout = result.stdout.split()[-3:]
    return int(size), int(overflow), float(timeout)


def test_pool_settings_come_from_environment() -> None:
    size, overflow, timeout = _pool(
        {"DATABASE_POOL_SIZE": "7", "DATABASE_MAX_OVERFLOW": "3", "DATABASE_POOL_TIMEOUT": "11"}
    )
    assert (size, overflow, timeout) == (7, 3, 11.0)


def test_web_defaults() -> None:
    assert _pool({}) == (10, 10, 30.0)


def test_worker_role_defaults_are_larger() -> None:
    assert _pool({"MANUS_PROCESS_ROLE": "worker"}) == (20, 20, 30.0)
