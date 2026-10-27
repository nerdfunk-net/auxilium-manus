"""Settings for the HTTP transport: bind address, allowed Host names and client tokens.

Over HTTP every client must present a bearer token, so a server without at least one valid
token refuses to start. Tokens come from ``MCP_CLIENT_TOKENS`` (``name=token`` pairs, comma
separated) and/or ``MCP_CLIENT_TOKENS_FILE`` (one ``name=token`` per line, ``#`` comments;
suited to Docker secrets).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from nautobot_mcp.config import ConfigError

MIN_TOKEN_LENGTH = 32
DEFAULT_PORT = 8000
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LOOPBACK_ALLOWED_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")
_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class ClientToken:
    name: str
    token: str = field(repr=False)  # never printed or logged


@dataclass(frozen=True)
class HttpConfig:
    host: str
    port: int
    allowed_hosts: tuple[str, ...]
    clients: tuple[ClientToken, ...]

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> HttpConfig:
        host = env.get("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"
        clients = _parse_clients(env)
        return cls(
            host=host,
            port=_parse_port(env.get("MCP_PORT", str(DEFAULT_PORT))),
            allowed_hosts=_parse_allowed_hosts(host, env.get("MCP_ALLOWED_HOSTS", "")),
            clients=clients,
        )


def _parse_port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise ConfigError("MCP_PORT must be a number between 1 and 65535")
    return port


def _parse_allowed_hosts(host: str, raw: str) -> tuple[str, ...]:
    given = tuple(part.strip() for part in raw.split(",") if part.strip())
    if host in LOOPBACK_HOSTS:
        return (*LOOPBACK_ALLOWED_HOSTS, *given)
    if not given:
        raise ConfigError(
            "MCP_ALLOWED_HOSTS must list the Host names clients use (for example "
            "nautobot-mcp:8000) when MCP_HOST is not a loopback address"
        )
    return given


def _parse_clients(env: Mapping[str, str]) -> tuple[ClientToken, ...]:
    entries = [part for part in env.get("MCP_CLIENT_TOKENS", "").split(",")]
    entries += _read_token_file(env.get("MCP_CLIENT_TOKENS_FILE", "").strip())
    clients: list[ClientToken] = []
    for entry in (e.strip() for e in entries):
        if entry:
            clients.append(_parse_entry(entry))
    if not clients:
        raise ConfigError(
            "at least one client token is required (MCP_CLIENT_TOKENS or MCP_CLIENT_TOKENS_FILE)"
        )
    names = [c.name for c in clients]
    for name in names:
        if names.count(name) > 1:
            raise ConfigError(f"duplicate client name '{name}'")
    if len({c.token for c in clients}) != len(clients):
        raise ConfigError("two clients share the same token; every client needs its own")
    return tuple(clients)


def _read_token_file(path: str) -> list[str]:
    if not path:
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError("MCP_CLIENT_TOKENS_FILE cannot be read") from exc
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _parse_entry(entry: str) -> ClientToken:
    name, separator, token = entry.partition("=")
    name, token = name.strip(), token.strip()
    if not separator:
        raise ConfigError("client tokens must be written name=token")  # never echo the entry
    if not _NAME.match(name):
        raise ConfigError(f"client name '{name}' must be 1-64 letters, digits, '.', '_' or '-'")
    if re.search(r"\s", token):
        raise ConfigError(f"token of client '{name}' must not contain whitespace")
    if len(token) < MIN_TOKEN_LENGTH:
        raise ConfigError(
            f"token of client '{name}' must be at least {MIN_TOKEN_LENGTH} characters"
        )
    return ClientToken(name=name, token=token)
