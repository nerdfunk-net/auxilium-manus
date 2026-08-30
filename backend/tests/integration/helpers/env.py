"""Typed accessors for the ``backend/.env.test`` lab values.

``conftest.py`` calls ``load_dotenv(.env.test)`` at import time, so by the time
any test runs these values are in ``os.environ``. Everything here is a plain
read — no defaults that would let a test silently run against the wrong host.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set in backend/.env.test")
    return value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class NautobotEnv:
    url: str
    token: str
    timeout: int
    verify_ssl: bool


@dataclass(frozen=True)
class GitRepoEnv:
    url: str
    token: str
    username: str
    branch: str
    verify_ssl: bool


@dataclass(frozen=True)
class CiscoEnv:
    host: str
    username: str
    password: str


def nautobot() -> NautobotEnv:
    return NautobotEnv(
        url=_require("NAUTOBOT_HOST"),
        token=_require("NAUTOBOT_TOKEN"),
        timeout=int(os.environ.get("NAUTOBOT_TIMEOUT", "30")),
        verify_ssl=_bool("NAUTOBOT_VERIFY_SSL", False),
    )


def git_repo() -> GitRepoEnv:
    return GitRepoEnv(
        url=_require("GIT_TEST_REPO_URL"),
        token=_require("GIT_TEST_REPO_TOKEN"),
        username=os.environ.get("GIT_TEST_REPO_USERNAME", "admin"),
        branch=os.environ.get("GIT_TEST_REPO_BRANCH", "main"),
        verify_ssl=_bool("GIT_TEST_REPO_VERIFY_SSL", False),
    )


def cisco() -> CiscoEnv:
    return CiscoEnv(
        host=_require("CISCO_DEVICE"),
        username=_require("CISCO_DEVICE_USERNAME"),
        password=_require("CISCO_DEVICE_PASSWORD"),
    )


def redis_configured() -> bool:
    return bool(os.environ.get("MANUS_REDIS_HOST", "").strip())
