"""``config.yaml`` of this agent: the Nautobot connection, the scan limits and DNS.

Transport settings (agent id, secret, ports) stay in the environment (``config.py``). The Nautobot
token comes from the environment variable named by ``nautobot.token_env`` (preferred) or, for
convenience, from ``nautobot.token``; neither value ever appears in an error message or a ``repr``.
The scan limits are decided by whoever runs this agent, never by the workflow author.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from manus_agent.hostpolicy import host_blocked
from manus_agent.ranges import IPv4Network, parse_networks

DEFAULT_PATH = "config.yaml"
CONFIG_ENV = "MANUS_AGENT_CONFIG"
MAX_CONFIG_BYTES = 256 * 1024
MAX_HOSTS_CEILING = 65_536
# Without allowed_networks only private (RFC 1918) space is scanned; reaching the internet must be
# an explicit choice of the operator (for example 0.0.0.0/0).
DEFAULT_ALLOWED = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


class ConfigFileError(ValueError):
    """config.yaml is unusable; the message never contains the token."""


@dataclass(frozen=True)
class NautobotSettings:
    url: str
    token: str = field(repr=False)
    verify_ssl: bool = True
    timeout_seconds: float = 15.0
    max_prefixes: int = 100


@dataclass(frozen=True)
class ScanSettings:
    count: int
    timeout_ms: int
    max_hosts: int
    allowed: tuple[IPv4Network, ...]


@dataclass(frozen=True)
class DnsSettings:
    enabled: bool
    timeout_seconds: float


@dataclass(frozen=True)
class InventoryConfig:
    nautobot: NautobotSettings
    scan: ScanSettings
    dns: DnsSettings


def _section(raw: Mapping[str, Any], key: str, allowed: set[str], *, required: bool) -> dict:
    value = raw.get(key)
    if value is None:
        if required:
            raise ConfigFileError(f"{key}: section is required")
        return {}
    if not isinstance(value, Mapping):
        raise ConfigFileError(f"{key}: must be a mapping")
    unknown = sorted(str(k) for k in set(value) - allowed)
    if unknown:
        raise ConfigFileError(f"{key}: unknown key {unknown[0]!r}")
    return dict(value)


def _number(
    section: Mapping[str, Any],
    label: str,
    name: str,
    default: float,
    low: float,
    high: float,
    *,
    whole: bool,
) -> float:
    value = section.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int if whole else (int, float)):
        raise ConfigFileError(f"{label}.{name}: must be {'a whole ' if whole else 'a '}number")
    if not low <= value <= high:
        raise ConfigFileError(f"{label}.{name}: must be between {low:g} and {high:g}")
    return value


def _flag(section: Mapping[str, Any], label: str, name: str, default: bool) -> bool:
    value = section.get(name, default)
    if not isinstance(value, bool):
        raise ConfigFileError(f"{label}.{name}: must be true or false")
    return value


def _url(section: Mapping[str, Any]) -> str:
    value = section.get("url")
    if not isinstance(value, str) or not value.strip():
        raise ConfigFileError("nautobot.url: a non-empty text is required")
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigFileError("nautobot.url: must be an http:// or https:// URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigFileError("nautobot.url: no credentials, query or fragment in the URL")
    if host_blocked(parts.hostname, loopback_blocked=False):
        # Loopback stays allowed (Nautobot may run on this host); the rest would get the token.
        raise ConfigFileError(
            "nautobot.url: this host is not allowed (link-local, multicast, unspecified or a "
            "cloud metadata name)"
        )
    return value.strip().rstrip("/")


def _token(section: Mapping[str, Any], env: Mapping[str, str]) -> str:
    """The environment variable wins over a token written into the file."""
    token_env = section.get("token_env")
    if token_env is not None:
        if not isinstance(token_env, str) or not _ENV_NAME.fullmatch(token_env):
            raise ConfigFileError("nautobot.token_env: not a valid environment variable name")
        from_env = env.get(token_env, "").strip()
        if from_env:
            return from_env
    inline = section.get("token")
    if inline is not None and (not isinstance(inline, str) or not inline.strip()):
        raise ConfigFileError("nautobot.token: must be a non-empty text")
    if inline:
        return inline.strip()
    where = f"environment variable {token_env} is not set" if token_env else "no token given"
    raise ConfigFileError(f"nautobot: {where} (set nautobot.token_env or nautobot.token)")


def _allowed(section: Mapping[str, Any]) -> tuple[IPv4Network, ...]:
    raw = section.get("allowed_networks")
    if raw is None or raw == [] or raw == "":
        text = DEFAULT_ALLOWED
    elif isinstance(raw, str):
        text = raw
    elif isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        text = ",".join(raw)
    else:
        raise ConfigFileError("scan.allowed_networks: must be a list of IPv4 networks")
    try:
        return parse_networks(text) or parse_networks(DEFAULT_ALLOWED)
    except ValueError as exc:
        raise ConfigFileError("scan.allowed_networks: not a list of IPv4 networks") from exc


def parse_inventory_config(raw: Any, env: Mapping[str, str]) -> InventoryConfig:
    if not isinstance(raw, Mapping):
        raise ConfigFileError("the file must contain a mapping")
    unknown = sorted(str(k) for k in set(raw) - {"nautobot", "scan", "resolve_dns"})
    if unknown:
        raise ConfigFileError(f"unknown section {unknown[0]!r}")
    nautobot = _section(
        raw,
        "nautobot",
        {"url", "token", "token_env", "verify_ssl", "timeout_seconds", "max_prefixes"},
        required=True,
    )
    scan = _section(
        raw, "scan", {"count", "timeout_ms", "max_hosts", "allowed_networks"}, required=False
    )
    dns = _section(raw, "resolve_dns", {"enabled", "timeout_seconds"}, required=False)
    return InventoryConfig(
        nautobot=NautobotSettings(
            url=_url(nautobot),
            token=_token(nautobot, env),
            verify_ssl=_flag(nautobot, "nautobot", "verify_ssl", True),
            timeout_seconds=float(
                _number(nautobot, "nautobot", "timeout_seconds", 15, 1, 120, whole=False)
            ),
            max_prefixes=int(
                _number(nautobot, "nautobot", "max_prefixes", 100, 1, 1000, whole=True)
            ),
        ),
        scan=ScanSettings(
            count=int(_number(scan, "scan", "count", 1, 1, 5, whole=True)),
            timeout_ms=int(_number(scan, "scan", "timeout_ms", 500, 50, 5000, whole=True)),
            max_hosts=int(
                _number(scan, "scan", "max_hosts", 4096, 1, MAX_HOSTS_CEILING, whole=True)
            ),
            allowed=_allowed(scan),
        ),
        dns=DnsSettings(
            enabled=_flag(dns, "resolve_dns", "enabled", False),
            timeout_seconds=float(
                _number(dns, "resolve_dns", "timeout_seconds", 2, 0.5, 10, whole=False)
            ),
        ),
    )


def load_inventory_config(env: Mapping[str, str] | None = None) -> InventoryConfig:
    """Read the file named by ``MANUS_AGENT_CONFIG`` (default ``config.yaml``)."""
    environment = os.environ if env is None else env
    path = Path(environment.get(CONFIG_ENV, "").strip() or DEFAULT_PATH)
    try:
        if path.stat().st_size > MAX_CONFIG_BYTES:
            raise ConfigFileError(f"{path}: larger than {MAX_CONFIG_BYTES} bytes")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigFileError(f"{path}: cannot be read ({exc.strerror or 'error'})") from exc
    except yaml.YAMLError as exc:
        raise ConfigFileError(f"{path}: is not valid YAML") from exc
    try:
        return parse_inventory_config(raw, environment)
    except ConfigFileError as exc:
        raise ConfigFileError(f"{path}: {exc}") from exc
