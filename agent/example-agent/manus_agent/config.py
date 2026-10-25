"""Agent configuration from environment variables (see .env.example)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from manus_agent.envelope import MIN_AGENT_SECRET_LENGTH

AGENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
VERSION = "1.0.0"
# The default is every interface because the usual deployment is a container; the app's HTTP
# transport reaches it over the Docker network, and the payload is encrypted either way.
ALL_INTERFACES = "0.0.0.0"  # noqa: S104
_REDIS_SCHEMES = ("redis://", "rediss://", "unix://")
DEFAULT_BODY = 16 * 1_048_576


class ConfigError(ValueError):
    """The environment does not describe a usable agent (never contains the secret)."""


@dataclass(frozen=True)
class AgentConfig:
    agent_id: str
    secret: str = field(repr=False)
    http_host: str
    http_port: int | None
    redis_url: str | None = field(repr=False)
    handlers_dir: Path
    max_concurrency: int
    max_body_bytes: int
    max_response_bytes: int
    loglevel: str
    version: str = VERSION


def _int(env: Mapping[str, str], name: str, default: int | None, low: int, high: int) -> int | None:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a whole number") from exc
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return value


def load_config(env: Mapping[str, str]) -> AgentConfig:
    agent_id = env.get("MANUS_AGENT_ID", "").strip()
    if not AGENT_ID_PATTERN.fullmatch(agent_id):
        raise ConfigError(
            "MANUS_AGENT_ID must start with a lowercase letter and use only lowercase letters, "
            "digits, '_' and '-' (max 64 characters); it must equal the Agent ID of the source"
        )
    secret = env.get("MANUS_AGENT_SECRET", "")
    if not secret:
        raise ConfigError("MANUS_AGENT_SECRET is required")
    if len(secret) < MIN_AGENT_SECRET_LENGTH:
        raise ConfigError(
            f"MANUS_AGENT_SECRET must be at least {MIN_AGENT_SECRET_LENGTH} characters "
            "(for example: openssl rand -base64 32)"
        )

    http_port = _int(env, "MANUS_AGENT_HTTP_PORT", None, 1, 65535)
    redis_url = env.get("MANUS_AGENT_REDIS_URL", "").strip() or None
    if redis_url is not None and not redis_url.startswith(_REDIS_SCHEMES):
        raise ConfigError("MANUS_AGENT_REDIS_URL must start with redis://, rediss:// or unix://")
    if http_port is None and redis_url is None:
        raise ConfigError(
            "set MANUS_AGENT_HTTP_PORT (HTTP transport) and/or MANUS_AGENT_REDIS_URL "
            "(Redis transport)"
        )

    return AgentConfig(
        agent_id=agent_id,
        secret=secret,
        http_host=env.get("MANUS_AGENT_HTTP_HOST", ALL_INTERFACES).strip() or ALL_INTERFACES,
        http_port=http_port,
        redis_url=redis_url,
        handlers_dir=Path(env.get("MANUS_AGENT_HANDLERS_DIR", "handlers")),
        max_concurrency=_int(env, "MANUS_AGENT_MAX_CONCURRENCY", 4, 1, 64) or 4,
        max_body_bytes=_int(env, "MANUS_AGENT_MAX_BODY_BYTES", DEFAULT_BODY, 1_024, 64 * 1_048_576)
        or DEFAULT_BODY,
        max_response_bytes=_int(
            env, "MANUS_AGENT_MAX_RESPONSE_BYTES", DEFAULT_BODY, 1_024, 64 * 1_048_576
        )
        or DEFAULT_BODY,
        loglevel=env.get("MANUS_AGENT_LOGLEVEL", "INFO").strip().upper() or "INFO",
    )
