"""Environment-driven configuration for the pyATS shim."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


# The token is the only thing between the network and device credentials: refuse a guessable one.
MIN_TOKEN_LENGTH = 32


@dataclass(frozen=True)
class ShimSettings:
    token: str
    port: int
    max_concurrent_jobs: int
    job_timeout_seconds: float
    pyats_bin: str


@lru_cache
def get_settings() -> ShimSettings:
    token = os.environ.get("PYATS_SHIM_TOKEN", "")
    if len(token) < MIN_TOKEN_LENGTH:
        raise RuntimeError(
            f"PYATS_SHIM_TOKEN must be set and at least {MIN_TOKEN_LENGTH} characters "
            "(openssl rand -hex 32)"
        )
    return ShimSettings(
        token=token,
        port=int(os.environ.get("PYATS_SHIM_PORT", "8100")),
        max_concurrent_jobs=int(os.environ.get("PYATS_SHIM_MAX_CONCURRENT_JOBS", "4")),
        job_timeout_seconds=float(
            os.environ.get("PYATS_SHIM_JOB_TIMEOUT_SECONDS", "120")
        ),
        pyats_bin=os.environ.get("PYATS_SHIM_PYATS_BIN", "pyats"),
    )
